(function(){
  const select=document.getElementById('fromEmployee');
  const balance=document.getElementById('reviewerBalance');
  if(!select||!balance)return;
  function sync(){const option=select.options[select.selectedIndex];balance.textContent=((option&&option.dataset.available)||'0')+'T';}
  select.addEventListener('change',sync);sync();
})();
