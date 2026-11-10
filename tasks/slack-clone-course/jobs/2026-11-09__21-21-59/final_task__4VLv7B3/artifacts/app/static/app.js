(() => {
  const $ = (s) => document.querySelector(s), token = () => localStorage.getItem('huddle.token');
  const api = async (url, opts={}) => {
    opts.headers = Object.assign({'Content-Type':'application/json'}, opts.headers||{});
    if (token()) opts.headers.Authorization = 'Bearer '+token();
    const r = await fetch('/api'+url, opts), data = await r.json().catch(()=>({}));
    if (!r.ok) throw new Error(data.error||'Request failed');
    return data;
  };
  let workspace=null, channel=null;
  const modal=$('#auth-modal'), form=$('[data-testid=auth-form]'), error=form.querySelector('.error');
  function showAuth(){modal.hidden=false;$('#app').style.visibility='hidden'}
  function showApp(){modal.hidden=true;$('#app').style.visibility='visible'}
  async function load(){
    try {
      const me=await api('/auth/me'); $('[data-testid=current-user]').textContent=me.user.username;
      const all=await api('/workspaces');
      if(!all.workspaces.length){$('[data-testid=empty-state-create-workspace]').hidden=false; return} $('[data-testid=empty-state-create-workspace]').hidden=true;
      workspace=all.workspaces[0]; const d=await api('/workspaces/'+workspace.slug);
      $('.ws-name').textContent=workspace.name; const list=$('[data-testid=channel-list]'); list.innerHTML='';
      d.channels.forEach(c=>{const li=document.createElement('li');li.dataset.testid='channel-entry';li.dataset.channelId=c.id;li.dataset.channelName=c.name;li.className='channel-entry';li.textContent='# '+c.name;li.onclick=()=>select(c);list.appendChild(li)});
      if(d.channels[0]) select(d.channels[0]);
    } catch(e){ showAuth(); }
  }
  async function select(c){channel=c; $('[data-testid=channel-title]').textContent='#'+c.name; $('[data-testid=channel-topic]').textContent=c.topic||''; try{const d=await api('/channels/'+c.id+'/messages'); render(d.messages)}catch(e){}}
  async function openThread(m){const panel=$('[data-testid=thread-panel]');panel.hidden=false;const box=panel.querySelector('.thread-messages');box.innerHTML='<div class="thread-parent">'+esc(m.body)+'</div>';const loadReplies=async()=>{const d=await api('/messages/'+m.id+'/replies');box.innerHTML='<div class="thread-parent">'+esc(m.body)+'</div>'+d.replies.map(x=>'<div>'+esc(x.body)+'</div>').join('')};await loadReplies();const f=panel.querySelector('form');f.onsubmit=async e=>{e.preventDefault();const i=$('[data-testid=thread-input]');if(!i.value.trim())return;await api('/channels/'+m.channel_id+'/messages',{method:'POST',body:JSON.stringify({body:i.value,parent_id:m.id})});i.value='';await loadReplies();select(channel)}}
  $('[data-testid=close-thread]').onclick=()=>{$('[data-testid=thread-panel]').hidden=true};
  function render(ms){const box=$('[data-testid=message-list]');box.innerHTML=''; if(!ms.length){box.innerHTML='<div class="empty-copy">No messages yet. Start the conversation.</div>';return} ms.slice().reverse().forEach(m=>{const row=document.createElement('div');row.dataset.testid='message';row.dataset.messageId=m.id;row.className='message';
      row.innerHTML='<strong>'+esc(m.author.display_name||m.author.username)+'</strong> <time>'+new Date(m.created_at).toLocaleString()+'</time><div data-testid="message-body">'+esc(m.body)+(m.edited_at?' <span class="edited">(edited)</span>':'')+'</div><span class="reply-count">'+(m.reply_count||0)+' '+((m.reply_count||0)===1?'reply':'replies')+'</span><button type="button" data-action="edit">Edit</button><button type="button" data-action="delete">Delete</button><button type="button" data-testid="open-thread-btn">Replies</button><button type="button" data-testid="reaction-button">😀</button><div data-testid="emoji-picker" hidden><button data-testid="emoji-option">😀</button><button data-testid="emoji-option">👍</button><button data-testid="emoji-option">❤️</button><button data-testid="emoji-option">🎉</button><button data-testid="emoji-option">🚀</button><button data-testid="emoji-option">✅</button><button data-testid="emoji-option">😂</button><button data-testid="emoji-option">🔥</button></div><div class="reactions"></div>';
      row.querySelector('[data-action=edit]').onclick=()=>{const i=document.createElement('input');i.name='edit-body';i.value=m.body;row.appendChild(i);i.focus();i.onkeydown=async e=>{if(e.key==='Enter'){await api('/messages/'+m.id,{method:'PATCH',body:JSON.stringify({body:i.value})});select(channel)}}};
      row.querySelector('[data-action=delete]').onclick=async()=>{await api('/messages/'+m.id,{method:'DELETE'});select(channel)};
      row.querySelector('[data-testid=open-thread-btn]').onclick=()=>openThread(m); row.querySelector('[data-testid=reaction-button]').onclick=()=>row.querySelector('[data-testid=emoji-picker]').hidden=false;
      row.querySelectorAll('[data-testid=emoji-option]').forEach(o=>o.onclick=async()=>{await api('/messages/'+m.id+'/reactions',{method:'POST',body:JSON.stringify({emoji:o.textContent})});row.querySelector('[data-testid=emoji-picker]').hidden=true;const chip=document.createElement('button');chip.dataset.testid='reaction-chip';chip.textContent=o.textContent+' 1';chip.onclick=async()=>{await api('/messages/'+m.id+'/reactions/'+encodeURIComponent(o.textContent),{method:'DELETE'});chip.remove()};row.querySelector('.reactions').appendChild(chip)});
      box.appendChild(row)})}
  function esc(x){return String(x).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
  form.onsubmit=async e=>{e.preventDefault();error.textContent='';const b=new FormData(form), mode=form.dataset.mode;try{const d=await api('/auth/'+(mode==='signup'?'register':'login'),{method:'POST',body:JSON.stringify({username:b.get('username'),password:b.get('password'),display_name:b.get('display_name')})});localStorage.setItem('huddle.token',d.token);showApp();load()}catch(x){error.textContent=x.message}};
  $('[data-testid=auth-toggle]').onclick=()=>{const signup=form.dataset.mode!=='signup';form.dataset.mode=signup?'signup':'login';$('.auth-title').textContent=signup?'Create your Huddle account':'Log in to Huddle';$('[data-testid=auth-submit]').textContent=signup?'Sign up':'Log in';form.querySelector('.signup-only').hidden=!signup};
  $('[data-testid=logout-btn]').onclick=()=>{localStorage.removeItem('huddle.token');showAuth()};
  $('[data-testid=send-btn]').closest('form').onsubmit=async e=>{e.preventDefault();const i=$('[data-testid=message-input]');if(!i.value.trim()||!channel)return;try{await api('/channels/'+channel.id+'/messages',{method:'POST',body:JSON.stringify({body:i.value})});i.value='';select(channel)}catch(x){}};
  $('[data-testid=workspace-create-form]').onsubmit=async e=>{e.preventDefault();const b=new FormData(e.target);try{await api('/workspaces',{method:'POST',body:JSON.stringify({slug:b.get('slug'),name:b.get('name')})});await load()}catch(x){}};
  $('[data-testid=new-channel-btn]').onclick=()=>$('#create-channel-modal').hidden=false;
  $('[data-testid=create-channel-cancel]').onclick=()=>$('#create-channel-modal').hidden=true;
  $('[data-testid=create-channel-form]').onsubmit=async e=>{e.preventDefault();const b=new FormData(e.target);try{const created=await api('/workspaces/'+workspace.slug+'/channels',{method:'POST',body:JSON.stringify({name:b.get('name'),is_private:b.get('is_private')==='on'})});$('#create-channel-modal').hidden=true;e.target.reset();await load();if(created.channel)select(created.channel)}catch(x){e.target.querySelector('.error').textContent=x.message}};
  const qt=new URLSearchParams(location.search).get('token'); if(qt){localStorage.setItem('huddle.token',qt)}
  if(token()){showApp();load()}else showAuth();
  setInterval(()=>{if(token()&&channel)select(channel)},1000);
})();
