from html import escape

from .service import EXPERIENCE, SPONSORSHIP

PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job Application Agent</title>
<style>
body{font-family:Inter,Arial,sans-serif;background:#f5f7fb;margin:0;color:#172033}
.wrap{max-width:1000px;margin:30px auto;padding:0 18px}.card{background:#fff;border:1px solid #e4e8f0;border-radius:14px;padding:22px;margin:14px 0}
h1{margin:0 0 6px}h2{margin:0 0 10px}.muted{color:#667085;font-size:14px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
label{font-weight:600;font-size:14px}input,textarea,select{width:100%;box-sizing:border-box;padding:10px;border:1px solid #ccd3df;border-radius:8px;margin-top:5px;font:inherit}
textarea{min-height:100px}.full{grid-column:1/-1}.checks{display:flex;gap:18px;flex-wrap:wrap;margin-top:6px}.checks label{font-weight:500}.checks input{width:auto}
button{background:#172033;color:#fff;border:0;border-radius:8px;padding:9px 15px;cursor:pointer;margin:2px}.secondary{background:#eef2f7;color:#172033}
.danger{background:#a12622}.privacy{border-top:1px solid #edf0f5;padding-top:14px;margin-top:8px}
.pill{display:inline-block;padding:3px 9px;border-radius:99px;background:#eef2ff;margin:2px;font-size:12px}.pill.warn{background:#fff1e6;color:#9a3412}.pill.gap{background:#f1f5f9}
.row{display:flex;justify-content:space-between;gap:15px;align-items:flex-start;border-top:1px solid #edf0f5;padding:13px 0}.score{font-size:20px;font-weight:700}
.status{position:sticky;top:0;padding:10px 14px;border-radius:8px;margin:10px 0;display:none}.status.ok{background:#e7f6ec;display:block}.status.bad{background:#fde8e8;display:block}
pre{white-space:pre-wrap;background:#f8fafc;border:1px solid #e4e8f0;border-radius:8px;padding:12px}.inline{display:flex;gap:8px;align-items:center}.inline select,.inline input{width:auto}
@media(max-width:700px){.grid{grid-template-columns:1fr}}
</style></head>
<body><div class="wrap">
<div class="card"><h1>Job Application Agent</h1><div class="muted">Profile, find jobs, review matches, prepare packets, track applications. You submit every application yourself.</div></div>
<div id="status" class="status"></div>

<form id="profile-form" class="card grid" method="post" action="/profile" enctype="multipart/form-data" onsubmit="saveProfile(event)">
<h2 class="full">1. Your profile</h2>
<label>Name<input name="full_name" value="[[full_name]]"></label>
<label>Email<input name="email" value="[[email]]"></label>
<label>Phone<input name="phone" value="[[phone]]"></label>
<label>LinkedIn URL<input name="linkedin" value="[[linkedin]]" placeholder="https://linkedin.com/in/..."></label>
<label>GitHub URL<input name="github" value="[[github]]" placeholder="https://github.com/..."></label>
<label>Target roles (comma separated)<input name="roles" value="[[roles]]" placeholder="AI Engineer, DevOps Engineer"></label>
<label>Preferred locations<input name="locations" value="[[locations]]" placeholder="Bengaluru, Hyderabad"></label>
<label>Experience level<select name="experience">[[experience_options]]</select></label>
<label>Key skills (blank = taken from your resume)<input name="skills" value="[[skills]]" placeholder="Python, AWS, Docker"></label>
<label>Minimum salary<input name="salary_min" value="[[salary_min]]" placeholder="e.g. 300000"></label>
<label>Maximum salary<input name="salary_max" value="[[salary_max]]" placeholder="e.g. 600000"></label>
<label>Notice period<input name="notice_period" value="[[notice_period]]" placeholder="Immediate / 30 days"></label>
<label>Work authorization<input name="visa" value="[[visa]]" placeholder="India citizen"></label>
<label>Sponsorship needed?<select name="sponsorship">[[sponsorship_options]]</select></label>
<label>Daily preparation limit<input type="number" name="daily_cap" value="[[daily_cap]]" min="1" max="100"></label>
<div class="full"><b>Work mode</b><div class="checks">
<label><input type="checkbox" name="remote" value="yes" [[remote]]> Remote</label>
<label><input type="checkbox" name="hybrid" value="yes" [[hybrid]]> Hybrid</label>
<label><input type="checkbox" name="onsite" value="yes" [[onsite]]> On-site</label></div></div>
<label class="full">Resume text<textarea name="resume_text">[[resume_text]]</textarea></label>
<label class="full">Or upload a resume (.txt, .pdf, .docx)<input type="file" name="resume" accept=".txt,.pdf,.docx"></label>
<div class="full"><button type="submit">Save profile and rescore jobs</button></div>
</form>
<div class="card privacy"><h2>Profile privacy</h2><p class="muted">Your profile and resume are stored locally in the app database and uploads folder. They are not encrypted. Deleting profile data also clears generated application packets and profile-based match scores, while keeping your job list and application status history.</p><button class="danger" onclick="clearProfile()">Delete profile data</button></div>

<div class="card"><h2>2. Add jobs</h2>
<div class="inline"><select id="kind"><option>greenhouse</option><option>lever</option></select>
<input id="token" placeholder="company board name, e.g. acme"><button onclick="fetchBoard()">Fetch from board</button></div>
<p class="muted">Or paste a JSON array: [{"url":"https://...","company":"Acme","title":"DevOps Trainee","location":"Bengaluru","description":"..."}]</p>
<textarea id="jobs"></textarea><button onclick="addJobs()">Add jobs</button></div>

<div class="card"><h2>3. Matches</h2>
<div class="inline"><label>Show <select id="filter" onchange="load()"><option value="">all</option><option>AWAITING_APPROVAL</option><option>LOW_MATCH</option><option>APPROVED</option><option>READY_TO_APPLY</option></select></label></div>
<p class="muted">AI review drafts feedback and a cover letter from the job and selected profile fields. Review it yourself; it never approves or submits.</p>
<div id="list">Loading...</div><pre id="agent-review" style="display:none"></pre></div>

<div class="card"><h2>4. Prepare and track</h2>
<p class="muted">"Prepare approved" builds a packet (resume lines + cover-letter draft) for each approved job, up to your daily limit. Open the job (or use Pre-fill form on Greenhouse/Lever pages), review, submit yourself, then mark it applied.</p>
<button onclick="batch()">Prepare approved</button> <a href="/export.csv"><button class="secondary">Export CSV</button></a>
<div id="report" class="muted"></div><div id="apps"></div><pre id="packet" style="display:none"></pre></div>
</div>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeUrl=u=>/^https?:\/\//i.test(u)?u:'#';
const post=(path,body)=>api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
async function api(path,opts){const r=await fetch(path,opts);let b=null;try{b=await r.json()}catch(e){}
  if(!r.ok)throw new Error((b&&b.detail)||r.statusText);return b}
function say(m,bad){const el=$('status');el.textContent=m;el.className='status '+(bad?'bad':'ok')}
async function act(fn){try{await fn()}catch(e){say(e.message,true)}await load()}
async function saveProfile(event){
  event.preventDefault();
  const button=$('profile-form').querySelector('button[type="submit"]');
  button.disabled=true; say('Saving profile...',false);
  try{
    const response=await fetch('/profile',{method:'POST',body:new FormData($('profile-form'))});
    if(!response.ok){const detail=(await response.text()).replace(/<[^>]*>/g,' ').trim().slice(0,240);throw new Error(`Save failed (${response.status}) ${detail}`)}
    say('Profile saved. Refreshing matches...',false);
    window.location.reload();
  }catch(error){say('Profile save failed: '+error.message,true);button.disabled=false}
}
async function clearProfile(){
  if(!window.confirm('Delete your saved profile, resume upload, generated application packets, and profile-based match scores? Job listings and application status history will remain.'))return;
  try{await post('/profile/delete');say('Profile data and generated packets deleted. Job and application history kept.',false);window.location.reload()}
  catch(error){say('Could not delete profile data: '+error.message,true)}
}
const addJobs=()=>act(async()=>{say('Added: '+JSON.stringify(await post('/jobs',JSON.parse($('jobs').value))))});
const fetchBoard=()=>act(async()=>{say('Fetched: '+JSON.stringify(await post('/connectors/fetch',{kind:$('kind').value,token:$('token').value})))});
const approve=id=>act(()=>post('/jobs/'+id+'/approve'));
const rejectJob=id=>act(()=>post('/jobs/'+id+'/reject'));
const prefill=id=>act(async()=>{const r=await post('/jobs/'+id+'/prefill');say(r.note)});
const agentReview=id=>act(async()=>{say('Preparing AI review...');const r=await post('/jobs/'+id+'/agent-review');const el=$('agent-review');el.textContent=JSON.stringify(r.review,null,2);el.style.display='block';say('AI review ready. Check each claim before using it.')});
const batch=()=>act(async()=>{say('Prepared: '+JSON.stringify(await post('/run-batch')))});
const setStatus=(id,status,fu)=>act(()=>post('/applications/'+id+'/status',{status:status,follow_up:fu||null}));
async function showPacket(id){try{const p=await api('/jobs/'+id+'/packet');const el=$('packet');
  el.textContent='Resume lines to highlight:\n- '+(p.resume_bullets.join('\n- ')||'(none found)')+'\n\nSkills to learn: '+(p.skills_to_learn.join(', ')||'-')+'\n\n'+p.cover_letter;
  el.style.display='block'}catch(e){say(e.message,true)}}
async function load(){
  const jobs=await api('/api/jobs');const f=$('filter').value;const shown=jobs.filter(j=>!f||j.status===f);
  $('list').innerHTML=shown.length?shown.map(j=>`<div class="row"><div><b>${esc(j.title)}</b> - ${esc(j.company)}<br><span class="muted">${esc(j.location)} | ${esc(j.status)}</span><br>`+
   j.reasons.map(x=>`<span class="pill${x.startsWith('Warning')?' warn':''}">${esc(x)}</span>`).join('')+
   (j.gaps.length?`<br><span class="pill gap">Skills to learn: ${esc(j.gaps.join(', '))}</span>`:'')+
   `</div><div><div class="score">${esc(j.score)}</div>`+
   (j.status==='AWAITING_APPROVAL'?`<button onclick="approve(${Number(j.id)})">Approve</button>`:'')+
   (j.status==='LOW_MATCH'?`<button class="secondary" onclick="approve(${Number(j.id)})">Approve anyway</button>`:'')+
   `<button class="secondary" onclick="agentReview(${Number(j.id)})">AI review</button>`+
   (['AWAITING_APPROVAL','LOW_MATCH','APPROVED'].includes(j.status)?`<button class="secondary" onclick="rejectJob(${Number(j.id)})">Reject</button>`:'')+
   `<br><a href="${esc(safeUrl(j.url))}" target="_blank" rel="noopener noreferrer">Open job</a></div></div>`).join(''):'No jobs yet.';
  const r=await api('/report');$('report').textContent=`Prepared today: ${r.queued_today}/${r.daily_cap} | Applied today: ${r.applied_today}`;
  const apps=await api('/applications');const opts=['READY_TO_APPLY','APPLIED','INTERVIEW','OFFER','REJECTED_BY_COMPANY','WITHDRAWN'];
  $('apps').innerHTML=apps.map(a=>`<div class="row"><div><b>${esc(a.title)}</b> - ${esc(a.company)}<br><a href="${esc(safeUrl(a.url))}" target="_blank" rel="noopener noreferrer">Open job</a> <button class="secondary" onclick="showPacket(${Number(a.job_id)})">Packet</button>`+(a.prefill?` <button class="secondary" onclick="prefill(${Number(a.job_id)})">Pre-fill form</button>`:'')+`</div>`+
   `<div class="inline"><select onchange="setStatus(${Number(a.job_id)},this.value,'${esc(a.follow_up||'')}')">${opts.map(o=>`<option${o===a.status?' selected':''}>${o}</option>`).join('')}</select>`+
   `<input type="date" value="${esc(a.follow_up||'')}" onchange="setStatus(${Number(a.job_id)},'${esc(a.status)}',this.value)"></div></div>`).join('');
}
load().catch(e=>say(e.message,true));
</script></body></html>"""


def _options(values, selected):
    return "".join(f'<option{" selected" if v == selected else ""}>{escape(v)}</option>' for v in values)


def render_home(profile: dict) -> str:
    p = profile or {}
    simple = ["full_name", "email", "phone", "linkedin", "github", "roles", "locations", "skills", "notice_period", "visa", "resume_text"]
    page = PAGE
    for k in simple:
        page = page.replace(f"[[{k}]]", escape(str(p.get(k) or ""), quote=True))
    for k in ("salary_min", "salary_max"):
        page = page.replace(f"[[{k}]]", escape(str(p.get(k) or "")))
    page = page.replace("[[daily_cap]]", escape(str(p.get("daily_cap") or 25)))
    page = page.replace("[[experience_options]]", _options(EXPERIENCE, p.get("experience") or "Fresher"))
    page = page.replace("[[sponsorship_options]]", _options(SPONSORSHIP, p.get("sponsorship") or "No"))
    for k in ("remote", "hybrid", "onsite"):  # unsaved profile = all on; saved profile = respect the user's choice
        on = p.get(k, 1) if p else 1
        page = page.replace(f"[[{k}]]", "checked" if on else "")
    return page
