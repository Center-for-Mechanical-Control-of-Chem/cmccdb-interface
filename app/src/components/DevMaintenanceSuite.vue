<script>
export default {
  data:()=>({running:false, token:null, results:[], plans:{}, backups:{}, error:null}),
  computed:{summary(){return JSON.stringify({results:this.results.map(r=>({...r,result:r.result.tables?{...r.result,tables:undefined,sequences:undefined,tables_verified:Object.keys(r.result.tables).length,rows_verified:Object.values(r.result.tables).reduce((n,t)=>n+t.rows,0)}:r.result})),plans:this.plans,backups:this.backups,error:this.error},null,2)}},
  methods:{
    async request(action,database,body,extra={}){
      const query=new URLSearchParams({database,...extra})
      const response=await fetch('/api/dev/maintenance_test/'+action+'?'+query,
        body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CMCCDB-CSRF':this.token,'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify(body)})
      const data=await response.json()
      if(!response.ok)throw new Error(JSON.stringify({status:response.status,data}))
      if(action!=='job' && (data.status==='queued'||data.status==='running')){
        for(let attempt=0;attempt<7200;attempt++){
          await new Promise(resolve=>setTimeout(resolve,500))
          const progress=await this.request('job',database,undefined,{id:data.id})
          if(progress.status==='complete')return progress.result
          if(progress.status==='failed')throw new Error(progress.error)
        }
        throw new Error('Maintenance job is still running; check its saved status')
      }
      return data
    },
    async authenticate(){
      const response=await fetch('/api/dev/maintenance_test/info')
      const data=await response.json()
      if(!response.ok)throw new Error('Maintenance requires a signed-in CMCC owner: '+response.status)
      this.token=data.csrf_token
    },
    async run(action){
      this.running=true;this.error=null
      try{
        await this.authenticate()
        if(action==='baseline')await this.request('setup_clients','staging',{})
        const databases=action==='restored_migration'?['staging','cmcc'].map(source=>{
          const restored=[...this.results].reverse().find(r=>r.action==='restore'&&r.database===source)
          if(!restored)throw new Error('Verify the backup before checking a restored copy')
          return restored.result.database
        }):['staging','cmcc']
        for(const database of databases){
          let result
          if(action==='baseline'){
            result=await this.request('backup',database,{record_baseline:true})
            this.backups[database]=result.id
          }else if(action==='restore'){
            if(!this.backups[database])throw new Error('Create a backup before restoring')
            result=await this.request('restore',database,{}, {id:this.backups[database]})
          }else if(action==='plan'){
            result=await this.request('migration',database)
            this.plans[database]=result
          }else if(action==='migration'||action==='restored_migration'){
            const preview=await this.request('migration',database)
            this.plans[database]=preview
            result=await this.request('migration',database,{fingerprint:preview.fingerprint})
          }
          this.results.push({action,database,result})
        }
      }catch(error){this.error=error.message}
      finally{this.running=false}
    },
  },
}
</script>
<template>
  <section class="dev-maintenance">
    <h2>Development database maintenance</h2>
    <p>Backups cover database tables and attachments. Restore verifies a separate database. Owner sign-in is required.</p>
    <button :disabled="running" @click="run('baseline')">Back up and record both baselines</button>
    <button :disabled="running || !backups.staging" @click="run('restore')">Verify both backups by restoring copies</button>
    <button :disabled="running" @click="run('plan')">Preview both migrations</button>
    <button :disabled="running" @click="run('migration')">Apply both backed-up migrations</button>
    <button :disabled="running" @click="run('restored_migration')">Check restored copies need no migration</button>
    <p role="status">{{running?'Maintenance in progress':'Maintenance idle'}}</p>
    <pre id="dev-maintenance-results">{{summary}}</pre>
  </section>
</template>
<style scoped>
.dev-maintenance{margin-top:2rem;padding:1rem;border:1px solid #9ca3af;background:#f8fafc}
button{margin:.3rem}pre{max-height:25rem;overflow:auto;white-space:pre-wrap;font-size:.75rem}
</style>
