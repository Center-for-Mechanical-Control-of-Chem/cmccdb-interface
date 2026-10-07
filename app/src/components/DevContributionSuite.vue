<script>
export default {
  data: () => ({ cases: [], mode: 'smoke', running: false, progress: '', results: [], error: null, policy: null }),
  async mounted() {
    try {
      const response = await fetch('/api/dev/dev_suite/manifest')
      if (!response.ok) throw new Error('Test workbook manifest is unavailable')
      this.cases = (await response.json()).cases
    } catch (error) { this.error = error.message }
  },
  computed: {
    summary() { return JSON.stringify({progress:this.progress, results:this.results, error:this.error, policy:this.policy}, null, 2) },
  },
  methods: {
    async run() {
      this.running = true
      this.results = []
      this.error = null
      try {
        const userResponse = await fetch('/api/user-info')
        const user = await userResponse.json()
        if (!user || !user.member) throw new Error('Sign in as a CMCC member to test both databases')
        const policyResponse = await fetch('/api/dev/dev_suite/policy')
        this.policy = await policyResponse.json()
        if (!policyResponse.ok || this.policy.backup_enabled !== false) throw new Error('GitHub backup guard is not active')
        const chosen = this.mode === 'smoke' ? this.cases.filter(c => c.category === 'schema apparatus' && !c.expected_rejection).slice(0,1) : this.cases
        for (const database of ['staging','cmcc']) {
          for (const item of chosen) {
            this.progress = database + ': ' + item.filename
            const suffix = new URLSearchParams({file:item.filename,database}).toString()
            const existingResponse = await fetch('/api/dev/dev_suite/validate?' + suffix)
            if (existingResponse.ok) {
              const existing = await existingResponse.json()
              if (existing.stored_reactions !== undefined) {
                this.results.push({file:item.filename,database,already_stored:true,validation:existing})
                continue
              }
            }
            const inputResponse = await fetch('/api/dev/dev_suite/file?file='+encodeURIComponent(item.filename))
            if (!inputResponse.ok) throw new Error('Could not load '+item.filename)
            const payload = new FormData()
            payload.append('uploadFile',await inputResponse.blob(),item.filename)
            for (const name of item.auxiliary || []) {
              const auxiliaryResponse = await fetch('/api/dev/dev_suite/auxiliary?name='+encodeURIComponent(name))
              if (!auxiliaryResponse.ok) throw new Error('Could not load auxiliary file '+name)
              payload.append('auxFile',await auxiliaryResponse.blob(),name)
            }
            const query = new URLSearchParams({database, name:'CMCCDB Development Test Runner',
              email:'cmccdb-test@example.invalid', origin_url:window.location.href,
              // Exercise the development guard with backups explicitly requested on main.
              perform_backup:database === 'cmcc' ? 'true' : 'false'})
            const upload = await fetch('/api/upload?'+query.toString(),{method:'POST',body:payload})
            const body = await upload.text()
            const result = {file:item.filename,database,upload_status:upload.status}
            if (!upload.ok) {
              result.error=body
              if (item.expected_rejection) {
                const validationResponse = await fetch('/api/dev/dev_suite/validate?'+suffix)
                result.validation = await validationResponse.json()
                result.passed = upload.status === 406 && result.validation.passed
              }
              this.results.push(result); continue
            }
            if (item.expected_rejection) { result.passed=false; result.error='Invalid input was accepted'; this.results.push(result); continue }
            const validationResponse = await fetch('/api/dev/dev_suite/validate?'+suffix)
            result.validation = await validationResponse.json()
            for (const name of item.auxiliary || []) {
              const id = result.validation.dataset_id
              const attachmentResponse = await fetch('/api/auxiliary/'+id+'/'+encodeURIComponent(name)+'?database='+database)
              const sourceResponse = await fetch('/api/dev/dev_suite/auxiliary?name='+encodeURIComponent(name))
              const actual = new Uint8Array(await attachmentResponse.arrayBuffer())
              const expected = new Uint8Array(await sourceResponse.arrayBuffer())
              result.auxiliary = result.auxiliary || []
              result.auxiliary.push({name,passed:attachmentResponse.ok && actual.length === expected.length && actual.every((x,i)=>x===expected[i])})
            }
            this.results.push(result)
          }
        }
        const afterResponse=await fetch('/api/dev/dev_suite/policy')
        const after=await afterResponse.json()
        this.policy.git_unchanged=JSON.stringify(after.data_repo)===JSON.stringify(this.policy.data_repo)
        this.progress='Complete'
      } catch(error) { this.error=error.message; this.progress='Stopped' }
      finally { this.running=false }
    },
  },
}
</script>

<template>
  <section class="dev-contribution-suite">
    <h2>Development contribution tests</h2>
    <p>Submit synthetic Excel datasets to staging and main, then verify stored data and attachments. GitHub backups are disabled.</p>
    <label for="suite-mode">Workbook selection</label>
    <select id="suite-mode" v-model="mode" :disabled="running">
      <option value="smoke">One workbook in both databases</option>
      <option value="all">All test workbooks in both databases</option>
    </select>
    <button type="button" :disabled="running || !cases.length" @click="run">Run contribution tests</button>
    <p role="status">{{ progress }}</p>
    <p>{{ results.length }} checks completed; {{ results.filter(r => r.passed || (r.validation && r.validation.passed && !(r.auxiliary || []).some(a => !a.passed))).length }} passed.</p>
    <pre id="dev-suite-results">{{ summary }}</pre>
  </section>
</template>

<style scoped>
.dev-contribution-suite { margin-top: 2rem; padding: 1rem; border: 1px solid #9ca3af; border-radius: .25rem; background: #f8fafc; }
h2 { font-size: 1.25rem; }
label, select, button { margin-right: .6rem; }
pre { max-height: 28rem; overflow: auto; white-space: pre-wrap; font-size: .75rem; }
</style>
