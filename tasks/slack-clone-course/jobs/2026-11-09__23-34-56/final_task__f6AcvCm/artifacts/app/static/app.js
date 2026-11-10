(() => {
  const $=s=>document.querySelector(s), T=n=>`[data-testid="${n}"]`;
  const qs=new URLSearchParams(location.search), supplied=qs.get('token');
  if(supplied)localStorage.setItem('huddle.token',supplied);
  let token=localStorage.getItem('huddle.token')||'', workspace=null, current=null, channels=[], authGeneration=0;
  const modal=$('#auth-modal'), auth=$(T('auth-form')), authErr=auth&&auth.querySelector('[role="alert"]');
  async function api(url,opt={}) {
    opt.headers=Object.assign({},opt.headers||{});
    if(opt.body && typeof opt.body!=='string'){opt.headers['Content-Type']='application/json';opt.body=JSON.stringify(opt.body)}
    if(token)opt.headers.Authorization='Bearer '+token;
    const r=await fetch(url,opt), d=await r.json().catch(()=>({}));
    if(!r.ok)throw Error(d.error||'Request failed'); return d;
  }
  function showApp(){if(modal){modal.hidden=true;modal.style.display='none'}}
  function entry(c){const e=document.createElement('li');e.setAttribute('data-testid','channel-entry');e.dataset.channelId=c.id;e.dataset.channelName=c.name;e.className='channel-entry';e.textContent='#'+c.name;e.onclick=()=>{current=c;$(T('channel-title')).textContent='#'+c.name;$(T('channel-topic')).textContent=c.topic||'';select(c)};return e}
  async function select(c){
    current=c; const title=$(T('channel-title')), topic=$(T('channel-topic')), list=$(T('message-list'));
    if(title)title.textContent='#'+c.name;if(topic)topic.textContent=c.topic||'';
    if(list)list.textContent='Loading…';
    try{const d=await api('/api/channels/'+c.id+'/messages');if(list){list.innerHTML='';if(!d.messages.length){list.textContent='No messages yet.'}else d.messages.slice().reverse().forEach(renderMessage)}}catch(e){if(list)list.textContent='Unable to load messages.'}
  }
  function renderMessage(m){
    const list=$(T('message-list')); if(!list)return;
    if(list.textContent==='No messages yet.'||list.textContent==='Loading…')list.innerHTML='';
    const row=document.createElement('div'); row.setAttribute('data-testid','message'); row.dataset.messageId=m.id;
    row.innerHTML='<span class="avatar">'+(m.author.username||'?')[0]+'</span> <b>'+m.author.username+'</b> <span data-testid="message-body"></span> <span class="edit-indicator"></span><span class="reply-count">'+(m.reply_count||0)+' replies</span><button type="button" data-testid="open-thread-btn">Thread</button><span class="toolbar"></span>';
    row.querySelector(T('message-body')).textContent=m.body;
    if(m.edited_at){const ed=row.querySelector('.edit-indicator');ed.textContent=' (edited)';ed.classList.add('edited')}
    const bar=row.querySelector('.toolbar');
    const edit=document.createElement('button'); edit.dataset.action='edit'; edit.textContent='Edit';
    edit.onclick=()=>{const input=document.createElement('input');input.name='edit-body';input.value=m.body;row.replaceChild(input,row.querySelector(T('message-body')));input.focus();input.onkeydown=async e=>{if(e.key==='Enter'){const d=await api('/api/messages/'+m.id,{method:'PATCH',body:{body:input.value}});m=d.message;renderUpdated(row,m)}}};
    const del=document.createElement('button');del.dataset.action='delete';del.textContent='Delete';
    del.onclick=async()=>{await api('/api/messages/'+m.id,{method:'DELETE'});row.remove()};
    const react=document.createElement('button');react.setAttribute('data-testid','reaction-button');react.textContent='😊';bar.append(edit,del,react);
    const picker=document.createElement('div');picker.setAttribute('data-testid','emoji-picker');picker.hidden=true;
    ['😀','😃','😄','😁','😆','😅','😂','🤣','😊','🔥'].forEach(em=>{const b=document.createElement('button');b.setAttribute('data-testid','emoji-option');b.textContent=em;b.onclick=async()=>{const d=await api('/api/messages/'+m.id+'/reactions',{method:'POST',body:{emoji:em}});picker.hidden=true;let chip=row.querySelector('[data-testid="reaction-chip"]');if(!chip){chip=document.createElement('button');chip.setAttribute('data-testid','reaction-chip');row.appendChild(chip)}const r=d.reactions.find(x=>x.emoji===em);chip.textContent=em+' '+(r?r.count:0);chip.onclick=async()=>{const z=await api('/api/messages/'+m.id+'/reactions/'+encodeURIComponent(em),{method:'DELETE'});chip.remove()}};picker.appendChild(b)});row.appendChild(picker);react.onclick=()=>picker.hidden=!picker.hidden;
    bar.append(edit,del);list.appendChild(row);
    const thread=row.querySelector('[data-testid="open-thread-btn"]');
    if(thread) thread.onclick=async()=>{const panel=$(T('thread-panel'));if(panel){panel.hidden=false;panel.dataset.parentId=m.id;const box=panel.querySelector('.thread-messages');if(box)box.textContent=m.body;}};

  }
  function renderUpdated(row,m){const input=row.querySelector('[name="edit-body"]');if(input){const span=document.createElement('span');span.setAttribute('data-testid','message-body');span.textContent=m.body;input.replaceWith(span)}row.querySelector('.edit-indicator').textContent=' (edited)';row.querySelector('.edit-indicator').classList.add('edited')}
  async function load(){
    const generation=authGeneration;
    if(!token){if(modal){modal.hidden=false;modal.style.display='flex'}return}
    showApp();
    try{
      const me=await api('/api/auth/me'); if(generation!==authGeneration||!token)return; showApp();$(T('current-user')).textContent=me.user.username;
      const all=await api('/api/workspaces');
      if(!all.workspaces.length){$(T('empty-state-create-workspace')).hidden=false;return}
      workspace=await api('/api/workspaces/'+all.workspaces[0].slug);
      $('.ws-name').textContent=workspace.workspace.name; channels=workspace.channels.filter(c=>!c.is_dm);
      const cl=$(T('channel-list'));cl.innerHTML='';channels.forEach(c=>cl.appendChild(entry(c)));
      if(channels[0]){ current=channels[0]; $(T('channel-title')).textContent='#'+channels[0].name; $(T('channel-topic')).textContent=channels[0].topic||''; $(T('message-list')).textContent='No messages yet.'; setTimeout(()=>{select(channels[0]);startLive()},50); }
    }catch(e){ const list=$(T('channel-list')); if(list && !list.children.length){ list.textContent='Unable to load channels.'; } }
  }
  if(auth)auth.onsubmit=async e=>{e.preventDefault();authErr.textContent='';const f=new FormData(auth),signup=auth.dataset.mode==='signup';try{const d=await api(signup?'/api/auth/register':'/api/auth/login',{method:'POST',body:{username:f.get('username'),password:f.get('password'),...(signup?{display_name:f.get('display_name')}: {})}});token=d.token;localStorage.setItem('huddle.token',token);$(T('current-user')).textContent=d.user.username;showApp();load()}catch(x){authErr.textContent=x.message}};
  $(T('auth-toggle')).onclick=()=>{const s=auth.dataset.mode!=='signup';auth.dataset.mode=s?'signup':'login';auth.querySelector('.auth-title').textContent=s?'Sign up for Huddle':'Log in to Huddle';$(T('auth-submit')).textContent=s?'Sign up':'Log in';auth.querySelector('.signup-only').hidden=!s};
  $(T('logout-btn')).onclick=()=>{authGeneration++;localStorage.removeItem('huddle.token');token='';workspace=null;current=null;channels=[];if(modal){modal.hidden=false;modal.style.display='flex'}const cl=$(T('channel-list'));if(cl)cl.innerHTML='';const ml=$(T('message-list'));if(ml)ml.textContent='';};
  const wf=$(T('workspace-create-form'));if(wf)wf.onsubmit=async e=>{e.preventDefault();const f=new FormData(wf);try{const d=await api('/api/workspaces',{method:'POST',body:{slug:f.get('slug'),name:f.get('name')}});workspace={workspace:d.workspace,channels:[d.general_channel]};channels=[d.general_channel];current=d.general_channel;$(T('empty-state-create-workspace')).hidden=true;$('.ws-name').textContent=d.workspace.name;$(T('channel-title')).textContent='#'+d.general_channel.name;$(T('channel-topic')).textContent=d.general_channel.topic||'';$(T('message-list')).textContent='No messages yet.';const cl=$(T('channel-list'));cl.innerHTML='';cl.appendChild(entry(d.general_channel))}catch(x){let a=wf.querySelector('[role="alert"]')||document.createElement('div');a.setAttribute('role','alert');a.textContent=x.message;wf.appendChild(a)}};
  let liveTimer=null, liveBusy=false, liveStarted=false;
  async function liveRefresh(){
    if(!token||!current||liveBusy||!liveStarted)return;
    liveBusy=true;
    try{
      const d=await api('/api/channels/'+current.id+'/messages');
      const list=$(T('message-list')), ids=new Set(Array.from(list.querySelectorAll('[data-testid="message"]')).map(x=>String(x.dataset.messageId)));
      d.messages.slice().reverse().forEach(m=>{if(!ids.has(String(m.id)))renderMessage(m)});
    }catch(e){} finally{liveBusy=false}
  }
  function startLive(){if(!liveStarted){liveStarted=true;liveTimer=setInterval(liveRefresh,1000)}}
  const mi=$(T('message-input')), sf=mi&&mi.closest('form');
  async function sendMessage(){
    if(!current||!mi||!mi.value.trim()) return;
    const body=mi.value.trim();
    try { await api('/api/channels/'+current.id+'/messages',{method:'POST',body:{body}}); mi.value=''; await select(current); }
    catch(e){}
  }
  if(sf) sf.onsubmit=e=>{e.preventDefault();sendMessage()};
  const threadForm=$(T('thread-send'))&&$(T('thread-send')).closest('form');
  if(threadForm) threadForm.onsubmit=async e=>{
    e.preventDefault();
    const input=$(T('thread-input')), panel=$(T('thread-panel')), parent=panel&&panel.dataset.parentId;
    if(!input||!input.value.trim()||!parent||!current)return;
    const text=input.value.trim();
    try{
      const d=await api('/api/channels/'+current.id+'/messages',{method:'POST',body:{body:text,parent_id:Number(parent)}});
      input.value='';
      const box=panel.querySelector('.thread-messages'), line=document.createElement('div');
      line.textContent=d.message.body; box.appendChild(line);
      const row=document.querySelector('[data-testid="message"][data-message-id="'+parent+'"]'), count=row&&row.querySelector('.reply-count');
      if(count){const n=(parseInt(count.textContent)||0)+1;count.textContent=n+' repl'+(n===1?'y':'ies')}
    }catch(e){}
  };
  const closeThread=$(T('close-thread')); if(closeThread)closeThread.onclick=()=>{const p=$(T('thread-panel'));if(p)p.hidden=true};
  const wsm=$('#workspace-settings-modal');
  async function openWorkspaceSettings(){
    if(!workspace||!wsm)return;
    wsm.hidden=false;
    const slug=workspace.workspace.slug;
    try{
      const d=await api('/api/workspaces/'+slug+'/members');
      const pane=$(T('settings-pane-members')); pane.innerHTML='';
      d.members.forEach(m=>{
        const row=document.createElement('div');row.setAttribute('data-testid','member-row');row.dataset.userId=m.user_id;
        const badge=document.createElement('span');badge.setAttribute('data-testid','role-badge');badge.textContent=m.role;row.appendChild(document.createTextNode(m.user.username+' '));row.appendChild(badge);
        if(m.user_id!==workspace.workspace.owner_id){
          const sel=document.createElement('select');sel.setAttribute('data-testid','role-select');
          ['member','admin','guest'].forEach(r=>{const o=document.createElement('option');o.value=r;o.textContent=r;o.selected=r===m.role;sel.appendChild(o)});
          sel.onchange=async()=>{const z=await api('/api/workspaces/'+slug+'/members/'+m.user_id,{method:'PATCH',body:{role:sel.value}});badge.textContent=z.member.role};
          row.appendChild(sel);
        }
        pane.appendChild(row);
      });
      $(T('settings-tab-members')).onclick=()=>showSettings('members');
      $(T('settings-tab-invitations')).onclick=()=>{showSettings('invitations');loadInvitations()};
      $(T('settings-tab-general')).onclick=()=>{showSettings('general');$(T('workspace-name-input')).value=workspace.workspace.name;$(T('workspace-join-mode')).value=workspace.workspace.join_mode};
      showSettings('members');
    }catch(e){}
  }
  function showSettings(name){
    ['members','invitations','general'].forEach(x=>{const p=$(T('settings-pane-'+x));if(p)p.hidden=x!==name});
  }
  async function loadInvitations(){
    try{const d=await api('/api/workspaces/'+workspace.workspace.slug+'/invitations'), list=$(T('invitations-list'));list.innerHTML='';d.invitations.forEach(i=>{const li=document.createElement('li');li.setAttribute('data-testid','invitation-code');li.textContent=i.code;list.appendChild(li)})}catch(e){}
  }
  const joinForm=$(T('join-workspace-form'));if(joinForm)joinForm.onsubmit=async e=>{e.preventDefault();const f=new FormData(joinForm),err=$(T('join-workspace-error'));try{await api('/api/invitations/'+f.get('code')+'/accept',{method:'POST'});if(err)err.hidden=true;await load()}catch(x){if(err){err.hidden=false;err.textContent=x.message}}};
  const csb=$(T('channel-settings-btn')), csm=$('#channel-settings-modal');
  async function openChannelSettings(){
   if(!current||!csm)return;csm.hidden=false;$(T('channel-settings-title')).textContent='#'+current.name;
   try{const d=await api('/api/channels/'+current.id+'/members'),list=$(T('channel-members-list'));list.innerHTML='';d.members.forEach(m=>{const r=document.createElement('li');r.setAttribute('data-testid','channel-member-row');r.textContent=m.username;list.appendChild(r)})}catch(e){}
   $(T('channel-add-member-submit')).onclick=async e=>{e.preventDefault();try{const z=await api('/api/channels/'+current.id+'/members',{method:'POST',body:{username:$(T('channel-add-member-input')).value}});const list=$(T('channel-members-list'));list.innerHTML='';z.members.forEach(m=>{const r=document.createElement('li');r.setAttribute('data-testid','channel-member-row');r.textContent=m.username;list.appendChild(r)})}catch(e){}};
   $(T('channel-topic-submit')).onclick=async e=>{e.preventDefault();const z=await api('/api/channels/'+current.id,{method:'PATCH',body:{topic:$(T('channel-topic-input')).value}});current=z.channel;$(T('channel-topic')).textContent=z.channel.topic};
   $(T('archive-channel-btn')).onclick=async()=>{const z=await api('/api/channels/'+current.id+'/archive',{method:'POST'});current=z.channel;$(T('archive-channel-btn')).hidden=true;$(T('unarchive-channel-btn')).hidden=false};
   $(T('unarchive-channel-btn')).onclick=async()=>{const z=await api('/api/channels/'+current.id+'/unarchive',{method:'POST'});current=z.channel;$(T('archive-channel-btn')).hidden=false;$(T('unarchive-channel-btn')).hidden=true};
  }
  if(csb)csb.onclick=openChannelSettings;const csc=$(T('channel-settings-close'));if(csc)csc.onclick=()=>{csm.hidden=true};
  const wsb=$(T('workspace-settings-btn'));if(wsb)wsb.onclick=openWorkspaceSettings;
  const wsc=$(T('workspace-settings-close'));if(wsc)wsc.onclick=()=>{wsm.hidden=true};
  const cib=$(T('create-invitation-btn'));if(cib)cib.onclick=()=>{$('#create-invitation-form').hidden=false};
  const cif=$('#create-invitation-form');if(cif)cif.onsubmit=async e=>{e.preventDefault();try{await api('/api/workspaces/'+workspace.workspace.slug+'/invitations',{method:'POST',body:{max_uses:Number(new FormData(cif).get('max_uses')||1)}});cif.hidden=true;loadInvitations()}catch(x){}};
  const wgf=document.querySelector('.general-form');if(wgf)wgf.onsubmit=async e=>{e.preventDefault();const d=await api('/api/workspaces/'+workspace.workspace.slug,{method:'PATCH',body:{name:$(T('workspace-name-input')).value,join_mode:$(T('workspace-join-mode')).value}});workspace.workspace=d.workspace;$('.ws-name').textContent=d.workspace.name};
  const cm=$('#create-channel-modal'), nf=$(T('new-channel-btn')), cf=$(T('create-channel-form'));
  if(nf)nf.onclick=()=>{cm.hidden=false};$(T('create-channel-cancel')).onclick=()=>cm.hidden=true;
  if(cf)cf.onsubmit=async e=>{e.preventDefault();const f=new FormData(cf),a=cf.querySelector('[role="alert"]')||document.createElement('div');a.setAttribute('role','alert');try{const d=await api('/api/workspaces/'+workspace.workspace.slug+'/channels',{method:'POST',body:{name:f.get('name'),is_private:f.get('is_private')==='on'}});a.textContent='';channels.push(d.channel);current=d.channel;$(T('channel-list')).appendChild(entry(d.channel));cm.hidden=true;$(T('channel-title')).textContent='#'+d.channel.name;$(T('channel-topic')).textContent=d.channel.topic||'';$(T('message-list')).textContent='No messages yet.'}catch(x){a.textContent=x.message;cf.appendChild(a)}};
  load();
})();
