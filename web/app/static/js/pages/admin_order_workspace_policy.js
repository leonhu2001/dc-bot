document.addEventListener('DOMContentLoaded', () => {
  const heading = Array.from(document.querySelectorAll('.mw-r8-editor-head h3'))
    .find((node) => node.textContent.trim() === '接單人員與分潤');

  if (heading && heading.parentElement) {
    const paragraph = heading.parentElement.querySelector('p');
    if (paragraph) {
      paragraph.textContent = '新制：基礎 80%＋掛名 3%＋直播 2%＋前月已發放薪資達 5000T 次月 2%。掛名與直播以客服審核通過的報單為準；舊單保留原制度。此工作區只保留管理端修正與手動分潤。';
    }
  }

  document.querySelectorAll('.mw-r8-inline-form').forEach((form) => {
    const checkbox = form.querySelector('input[name="enabled"][type="checkbox"]');
    if (!checkbox) return;

    const label = checkbox.closest('label');
    if (label) {
      Array.from(label.childNodes).forEach((node) => {
        if (node.nodeType !== Node.TEXT_NODE) return;
        if (!String(node.nodeValue || '').includes('掛名')) return;
        node.nodeValue = ' 管理端修正掛名（新制 +3%；舊單依原制度） ';
      });
    }

    const button = form.querySelector('button[type="submit"]');
    if (button && button.textContent.trim() === '套用') {
      button.textContent = '修正掛名';
    }
  });
});
