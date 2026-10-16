document.addEventListener('DOMContentLoaded',()=>{
  document.querySelectorAll('[data-open-cs-backend]').forEach((el)=>{
    el.setAttribute('target','_blank');
    el.setAttribute('rel','noopener noreferrer');
  });

  const syncWorkerLiveRow=(row)=>{
    const selected=row.querySelector('input[type="radio"][data-worker-streamed]:checked');
    const wrap=row.querySelector('[data-worker-stream-url-wrap]');
    const input=row.querySelector('[data-worker-stream-url]');
    if(!wrap||!input)return;
    const isLive=selected&&selected.value==='1';
    wrap.hidden=!isLive;
    input.required=Boolean(isLive&&!input.disabled);
    if(!isLive){input.setCustomValidity('');}
  };

  document.querySelectorAll('[data-worker-live-row]').forEach((row)=>{
    row.querySelectorAll('input[type="radio"][data-worker-streamed]').forEach((radio)=>{
      radio.addEventListener('change',()=>syncWorkerLiveRow(row));
    });
    syncWorkerLiveRow(row);
  });
});
