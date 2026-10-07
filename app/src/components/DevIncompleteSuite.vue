<script>
export default {
  data:()=>({running:false,results:[],error:null,progress:'',policy:null}),
  computed:{summary(){return JSON.stringify({progress:this.progress,results:this.results,error:this.error,policy:this.policy},null,2)}},
  methods:{async run(){
    this.running=true;this.results=[];this.error=null
    try{
      const policy=await fetch('/api/dev/incomplete_suite/policy');this.policy=await policy.json()
      if(!policy.ok||this.policy.backup_enabled!==false)throw new Error('Development GitHub backup guard is not active')
      const response=await fetch('/api/dev/incomplete_suite/manifest')
      const manifest=await response.json();if(!response.ok)throw new Error('Owner sign-in is required')
      for(const database of ['staging','cmcc'])for(const item of manifest.cases){
        this.progress=database+': '+item.source
        const suffix=new URLSearchParams({database,file:item.filename})
        const result={file:item.source,database,expected_rejection:item.expected_rejection}
        const existing=await fetch('/api/dev/incomplete_suite/validate?'+suffix)
        if(existing.ok){const check=await existing.json();if(check.stored){result.already_stored=true;result.validation=check;this.results.push(result);continue}}
        const input=await fetch('/api/dev/incomplete_suite/file?file='+encodeURIComponent(item.filename))
        if(!input.ok)throw new Error('Fixture unavailable: '+item.filename)
        const body=new FormData();body.append('uploadFile',await input.blob(),item.filename)
        const query=new URLSearchParams({database,name:'CMCCDB Development Test Runner',email:'cmccdb-test@example.invalid',origin_url:window.location.href,perform_backup:database==='cmcc'?'true':'false'})
        const upload=await fetch('/api/upload?'+query,{method:'POST',body})
        result.upload_status=upload.status
        if(!upload.ok)result.error=await upload.text()
        const validated=await fetch('/api/dev/incomplete_suite/validate?'+suffix)
        result.validation=await validated.json()
        result.passed=item.expected_rejection?upload.status===406&&result.validation.passed:upload.ok&&result.validation.passed
        this.results.push(result)
      }
      const after=await(await fetch('/api/dev/incomplete_suite/policy')).json()
      this.policy.git_unchanged=JSON.stringify(after.data_repo)===JSON.stringify(this.policy.data_repo)
      this.progress='Complete'
    }catch(error){this.error=error.message;this.progress='Stopped'}finally{this.running=false}
  }},
}
</script>
<template>
  <section class="dev-incomplete">
    <h2>Incomplete dataset checks</h2>
    <p>Try every original incomplete dataset and the two-sheet extruder test in staging and main. Rejected files are reported and remain unchanged.</p>
    <button :disabled="running" @click="run">Test incomplete datasets in both databases</button>
    <p role="status">{{progress}}</p>
    <p>{{results.length}} attempts; {{results.filter(r=>r.passed||r.validation?.passed).length}} expected outcomes verified.</p>
    <pre id="dev-incomplete-results">{{summary}}</pre>
  </section>
</template>
<style scoped>
.dev-incomplete{margin-top:2rem;padding:1rem;border:1px solid #9ca3af;background:#f8fafc}
pre{max-height:25rem;overflow:auto;white-space:pre-wrap;font-size:.75rem}
</style>
