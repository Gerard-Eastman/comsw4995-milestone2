(() => {
const $=(s,p=document)=>p.querySelector(s), $$=(s,p=document)=>[...p.querySelectorAll(s)];
let token=localStorage.getItem('huddle.token')||new URLSearchParams(location.search).get('token'), ws, ch, user;
const api=async(path,opt={})=>{opt.headers={...(opt.headers||{}),Authorization:'Bearer '+token};if(opt.body&&typeof opt.body!='string'){opt.headers['Content-Type']='application/json';opt.body=JSON.stringify(opt.body)}const r=await fetch('/api'+path,opt);let d={};try{d=await r.json()}catch{}if(!r.ok)throw Error(d.error||'Request failed');return d};
const auth=$('#auth-modal'), form=$('[data-testid=auth-form]'), alert=$('.error',form);
function showAuth(){auth.hidden=false;form.dataset.mode='login';$('.auth-title',form).textContent='Log in to Huddle';$('[data-testid=auth-submit]').textContent='Log in';$('.signup-only',form).style.display='none'}
function renderUser(){ $('[data-testid=current-user]').textContent=user.username }
async function load(){
 user=(await api('/auth/me')).user;renderUser();auth.hidden=true;
 let d=(await api('/workspaces')).workspaces;
 if(!d.length){$('[data-testid=empty-state-create-workspace]').hidden=false;return}
 ws=d[0];$('.ws-name').textContent=ws.name; $('[data-testid=workspace-header]').title=ws.slug;
 await loadWs()
}
async function loadWs(){
 let d=await api('/workspaces/'+ws.slug);ws=d.workspace;
 $('.ws-name').textContent=ws.name+' '+ws.slug;
 let list=$('[data-testid=channel-list');list.innerHTML='';
 d.channels.filter(x=>!x.is_dm).forEach(x=>{let li=document.createElement('li');li.dataset.testid='channel-entry';li.dataset.channelId=x.id;li.dataset.channelName=x.name;li.textContent='#'+x.name;li.onclick=()=>select(x);list.append(li)});
 if(d.channels.length)select(d.channels[0])
}
async function select(x){ch=x;$('.channel-header [data-testid=channel-title]').textContent='#'+x.name; $('[data-testid=channel-topic]').textContent=x.topic||'';await loadMessages()}
async function loadMessages(){
 if(!ch||window.__pickerBusy)return;let d=await api('/channels/'+ch.id+'/messages');if(window.__pickerBusy)return;let box=$("[data-testid=message-list]");box.innerHTML='';
 if(!d.messages.length){box.innerHTML='<div class="empty-copy">No messages yet. Start the conversation.</div>';return}
 d.messages.reverse().forEach(addMessage)
}
function addMessage(m){
 let row=document.createElement('div');row.dataset.testid='message';row.dataset.id=m.id;row.dataset.messageId=m.id;row.setAttribute('data-message-id',m.id);row.innerHTML='<span class="avatar">'+(m.author?.display_name||'U')[0]+'</span> <b>'+esc(m.author?.display_name||'')+'</b> <time>'+new Date(m.created_at).toLocaleString()+'</time><div data-testid="message-body">'+esc(m.body)+'</div>'+(m.edited_at?'<span class="edited">(edited)</span>':'')+'<span class="reply-count">'+(m.reply_count||0)+' '+((m.reply_count||0)==1?'reply':'replies')+'</span><button data-testid="open-thread-btn">Thread</button><button data-testid="reaction-button">😊</button><button data-action="edit">Edit</button><button data-action="delete">Delete</button>';
 $("[data-testid=message-list]").append(row);
 $('[data-testid=open-thread-btn]',row).onclick=()=>thread(m);
 $('[data-action=delete]',row).onclick=async()=>{await api('/messages/'+m.id,{method:'DELETE'});row.remove()};
 $('[data-action=edit]',row).onclick=()=>{let i=document.createElement('input');i.name='edit-body';i.value=m.body;row.replaceChild(i,$('[data-testid=message-body]',row));i.onkeydown=async e=>{if(e.key==='Enter'){let z=await api('/messages/'+m.id,{method:'PATCH',body:{body:i.value}});row.dataset.edited='true';row.innerHTML='<div data-testid="message-body">'+esc(z.message.body)+'</div><span class="edited">(edited)</span><span class="reply-count">'+(m.reply_count||0)+' replies</span><button data-testid="open-thread-btn">Thread</button><button data-testid="reaction-button">😊</button><button data-action="edit">Edit</button><button data-action="delete">Delete</button>';}}};
 $('[data-testid=reaction-button]',row).onclick=async()=>{let p=document.createElement('div');p.dataset.testid='emoji-picker';window.__pickerBusy=true;let c=document.createElement('span');c.dataset.testid='reaction-chip';c.textContent='😀 1';c.onclick=async()=>{await api('/messages/'+m.id+'/reactions/'+encodeURIComponent(c.dataset.emoji||'😀'),{method:'DELETE'});c.remove();window.__pickerBusy=false};row.append(c);['😀','👍','🔥','❤️','🎉','😂','🚀','✅','👏'].forEach(e=>{let b=document.createElement('button');b.dataset.testid='emoji-option';b.textContent=e;b.onclick=async()=>{c.dataset.emoji=e;c.textContent=e+' 1';p.remove();window.__pickerBusy=true;try{let z=await api('/messages/'+m.id+'/reactions',{method:'POST',body:{emoji:e}});let q=z.reactions.find(q=>q.emoji===e);if(q)c.textContent=e+' '+q.count}catch(err){c.remove();window.__pickerBusy=false}};p.append(b)});row.append(p)}
}
function thread(m){let p=$('[data-testid=thread-panel');p.hidden=false;$('.thread-messages',p).innerHTML='<div>'+esc(m.body)+'</div>';p.dataset.parent=m.id}
function esc(x){return String(x||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
form.onsubmit=async e=>{e.preventDefault();try{let f=new FormData(form),mode=form.dataset.mode==='signup'?'register':'login',d=await fetch('/api/auth/'+mode,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:f.get('username'),password:f.get('password'),display_name:f.get('display_name')})}),z=await d.json();if(!d.ok)throw Error(z.error||'Invalid input');token=z.token;localStorage.setItem('huddle.token',token);await load()}catch(x){alert.textContent=x.message;alert.style.display='block'}};
$('[data-testid=auth-toggle]').onclick=()=>{let up=form.dataset.mode!=='signup';form.dataset.mode=up?'signup':'login';$('.auth-title',form).textContent=up?'Sign up for Huddle':'Log in to Huddle';$('[data-testid=auth-submit]').textContent=up?'Sign up':'Log in';$('.signup-only',form).style.display=up?'block':'none'};
$('[data-testid=logout-btn]').onclick=()=>{localStorage.removeItem('huddle.token');token=null;showAuth()};
$('[data-testid=empty-state-create-workspace] form').onsubmit=async e=>{e.preventDefault();let f=new FormData(e.target);ws=(await api('/workspaces',{method:'POST',body:{slug:f.get('slug'),name:f.get('name')}})).workspace;await loadWs();$('[data-testid=empty-state-create-workspace]').hidden=true};
$('[data-testid=new-channel-btn]').onclick=()=>$('#create-channel-modal').hidden=false;
$('[data-testid=create-channel-cancel]').onclick=()=>$('#create-channel-modal').hidden=true;
$('[data-testid=create-channel-form]').onsubmit=async e=>{e.preventDefault();let f=new FormData(e.target);try{let z=await api('/workspaces/'+ws.slug+'/channels',{method:'POST',body:{name:f.get('name'),is_private:f.get('is_private')==='on'}});$('#create-channel-modal').hidden=true;await loadWs();select(z.channel)}catch(x){$('.error',e.target).textContent=x.message}};
$('[data-testid=send-btn]').closest('form').onsubmit=async e=>{e.preventDefault();let i=$('[data-testid=message-input'),body=i.value.trim();if(!body||!ch)return;let z=await api('/channels/'+ch.id+'/messages',{method:'POST',body:{body}});i.value='';let b=$("[data-testid=message-list]");$('.empty-copy',b)?.remove();addMessage(z.message)};
$('[data-testid=close-thread]').onclick=()=> $('[data-testid=thread-panel]').hidden=true;
$('[data-testid=thread-send]').closest('form').onsubmit=async e=>{e.preventDefault();let p=$('[data-testid=thread-panel'),i=$('[data-testid=thread-input');if(i.value.trim()){
 let z=await api('/channels/'+ch.id+'/messages',{method:'POST',body:{body:i.value,parent_id:+p.dataset.parent}});
 let d=document.createElement('div');d.textContent=z.message.body;$('.thread-messages',p).append(d);
 let parent=document.querySelector('[data-message-id="'+p.dataset.parent+'"]');
 if(parent){let q=$('.reply-count',parent);let n=(parseInt(q.textContent)||0)+1;q.textContent=n+' '+(n==1?'reply':'replies')}
 i.value=''
}};
if(token){load().catch(()=>{token=null;showAuth()});setInterval(()=>{if(token&&ch&&!window.__pickerBusy&&!document.querySelector('input[name=edit-body]'))loadMessages().catch(()=>{})},500)}else showAuth();
})();
