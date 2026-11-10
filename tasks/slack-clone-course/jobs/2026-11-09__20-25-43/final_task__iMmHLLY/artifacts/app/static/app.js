(()=>{const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
let token=localStorage.getItem('huddle.token')||new URLSearchParams(location.search).get('token'), me=null, ws=null, ch=null;
const api=async(path,opt={})=>{opt.headers=Object.assign({'Content-Type':'application/json'},opt.headers||{});if(token)opt.headers.Authorization='Bearer '+token;let r=await fetch('/api'+path,opt),x={};try{x=await r.json()}catch{}if(!r.ok)throw Error(x.error||'Request failed');return x};
const authModal=$('#auth-modal'), form=$('[data-testid=auth-form]'), alert=$('[data-testid=auth-form] [role=alert]');
function showAuth(){authModal.hidden=false;$('#app').classList.add('logged-out')}
function hideAuth(){authModal.hidden=true;$('#app').classList.remove('logged-out')}
function err(e,node=alert){if(node){node.textContent=e.message||String(e);node.hidden=false}}
function clear(node=alert){if(node){node.textContent='';node.hidden=true}}
function setMode(mode){form.dataset.mode=mode;let signup=mode==='signup';$('.auth-title',form).textContent=signup?'Create your Huddle account':'Log in to Huddle';$('input[name=display_name]',form).hidden=!signup;$('[data-testid=auth-submit]',form).textContent=signup?'Sign up':'Log in';$('[data-testid=auth-toggle]',form).textContent=signup?'Already have an account? Log in':'Need an account? Sign up';clear()}
$('[data-testid=auth-toggle]').onclick=()=>setMode(form.dataset.mode==='login'?'signup':'login');
form.onsubmit=async e=>{e.preventDefault();clear();let x=Object.fromEntries(new FormData(form));try{let z=await api(form.dataset.mode==='signup'?'/auth/register':'/auth/login',{method:'POST',body:JSON.stringify(x)});token=z.token;localStorage.setItem('huddle.token',token);hideAuth();await boot()}catch(ex){err(ex)}};
async function boot(){try{let z=await api('/auth/me');me=z.user; $('[data-testid=current-user]').textContent=me.username;let q=await api('/workspaces');if(!q.workspaces.length){$('.ws-name').textContent='';$('[data-testid=empty-state-create-workspace]').hidden=false;$('.channel-header').hidden=true;return}ws=q.workspaces[0];await loadWorkspace()}catch(e){localStorage.removeItem('huddle.token');token=null;showAuth()}}
async function loadWorkspace(){let z=await api('/workspaces/'+encodeURIComponent(ws.slug));ws=z.workspace;$('.ws-name').textContent=ws.name;$('[data-testid=empty-state-create-workspace]').hidden=true;$('.channel-header').hidden=false;let list=$('[data-testid=channel-list');list.innerHTML='';z.channels.forEach(x=>{let li=document.createElement('li');li.dataset.testid='channel-entry';li.dataset.channelId=x.id;li.dataset.channelName=x.name;li.textContent='#'+x.name;li.onclick=async()=>await selectChannel(x);list.append(li)});if(z.channels.length)selectChannel(z.channels[0])}
$('[data-testid=workspace-create-form]').onsubmit=async e=>{e.preventDefault();let x=Object.fromEntries(new FormData(e.target));try{let z=await api('/workspaces',{method:'POST',body:JSON.stringify(x)});ws=z.workspace;await loadWorkspace()}catch(ex){err(ex)}};
async function selectChannel(x){ch=x;$$('[data-testid=channel-entry]').forEach(a=>a.classList.toggle('selected',String(a.dataset.channelId)===String(x.id)));$('[data-testid=channel-title]').textContent='#'+x.name;$('[data-testid=channel-topic]').textContent=x.topic||'';await loadMessages()}
async function loadMessages(){let box=$('[data-testid=message-list');box.innerHTML='';try{let z=await api('/channels/'+ch.id+'/messages');if(!Array.isArray(z.messages)||!z.messages.length){box.innerHTML='<div class="empty-copy">No messages yet. Start the conversation.</div>';return}z.messages.slice().reverse().forEach(renderMessage)}catch(e){err(e)}}
function renderMessage(m){
 let row=document.createElement('div');row.dataset.testid='message';row.dataset.messageId=m.id;
 let a=document.createElement('b');a.className='author';a.textContent=(m.author?.display_name||m.author?.username||'User')+' ';
 let b=document.createElement('span');b.dataset.testid='message-body';b.textContent=m.body||'';row.append(a,b);
 if(m.edited_at){let i=document.createElement('em');i.className='edited';i.textContent=' (edited)';row.append(i)}
 let tools=document.createElement('span');tools.className='toolbar';
 let edit=document.createElement('button');edit.dataset.action='edit';edit.textContent='Edit';edit.onclick=()=>editMessage(row,m);
 let del=document.createElement('button');del.dataset.action='delete';del.textContent='Delete';del.onclick=async()=>{await api('/messages/'+m.id,{method:'DELETE'});row.remove()};
 let rc=document.createElement('span');rc.className='reply-count';rc.textContent=(m.reply_count||0)+' '+((m.reply_count||0)==1?'reply':'replies');row.append(rc);let thread=document.createElement('button');thread.dataset.testid='open-thread-btn';thread.textContent='Thread';thread.onclick=()=>openThread(m);
 let react=document.createElement('button');react.dataset.testid='reaction-button';react.textContent='😀';react.onclick=()=>picker(row,m);
 tools.append(edit,del,thread,react);row.append(tools);
 (m.reactions||[]).forEach(x=>{let q=document.createElement('button');q.dataset.testid='reaction-chip';q.textContent=x.emoji+' '+x.count;q.onclick=async()=>{await api('/messages/'+m.id+'/reactions/'+encodeURIComponent(x.emoji),{method:'DELETE'});loadMessages()};row.append(q)});
 $('[data-testid=message-list]').append(row)
}
function editMessage(row,m){
 let i=document.createElement('input');i.name='edit-body';i.value=m.body;row.replaceChildren(i);
 i.onkeydown=async e=>{if(e.key==='Enter'){try{let z=await api('/messages/'+m.id,{method:'PATCH',body:JSON.stringify({body:i.value})});renderMessage(z.message);row.remove()}catch(x){err(x)}}}
}
function picker(row,m){
 let p=document.createElement('div');p.dataset.testid='emoji-picker';
 ['😀','😀','👍','❤️','🎉','🔥','😂','👏','🚀','✅'].forEach(em=>{let o=document.createElement('button');o.dataset.testid='emoji-option';o.textContent=em;o.onclick=async()=>{await api('/messages/'+m.id+'/reactions',{method:'POST',body:JSON.stringify({emoji:em})});p.remove();loadMessages()};p.append(o)});row.append(p)
}
async function openThread(m){
 let panel=$('[data-testid=thread-panel]');panel.hidden=false;let box=$('.thread-messages',panel);box.innerHTML='<div class="thread-parent">'+(m.body||'')+'</div>';
 try{let z=await api('/messages/'+m.id+'/replies');z.replies.forEach(x=>{let d=document.createElement('div');d.textContent=x.body;box.append(d)})}catch(e){}
 let f=$('[data-testid=thread-send]',panel).closest('form');f.onsubmit=async e=>{e.preventDefault();let i=$('[data-testid=thread-input]');if(!i.value.trim())return;await api('/channels/'+m.channel_id+'/messages',{method:'POST',body:JSON.stringify({body:i.value,parent_id:m.id})});i.value='';openThread(m);loadMessages()}
}
$('[data-testid=close-thread]').onclick=()=> $('[data-testid=thread-panel]').hidden=true;
$('[data-testid=send-btn]').closest('form').onsubmit=async e=>{e.preventDefault();let i=$('[data-testid=message-input]');if(!i.value.trim()||!ch)return;try{await api('/channels/'+ch.id+'/messages',{method:'POST',body:JSON.stringify({body:i.value})});i.value='';loadMessages()}catch(ex){err(ex)}};
$('[data-testid=new-channel-btn]').onclick=()=>{$('#create-channel-modal').hidden=false};
$('[data-testid=create-channel-cancel]').onclick=()=>$('#create-channel-modal').hidden=true;
$('[data-testid=create-channel-form]').onsubmit=async e=>{e.preventDefault();let f=e.target,x={name:f.name.value,is_private:f.is_private.checked};try{let z=await api('/workspaces/'+ws.slug+'/channels',{method:'POST',body:JSON.stringify(x)});$('#create-channel-modal').hidden=true;await loadWorkspace();selectChannel(z.channel)}catch(ex){err(ex,$('[data-testid=create-channel-form] [role=alert]'))}};
$('[data-testid=logout-btn]').onclick=()=>{localStorage.removeItem('huddle.token');token=null;me=null;showAuth();setMode('login')};
if(token){hideAuth();boot();setInterval(()=>{if(token&&ch&&authModal.hidden)loadMessages()},1200)}else{showAuth();setMode('login')}
})();
