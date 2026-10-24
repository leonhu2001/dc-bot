(() => {
  "use strict";

  const rows = document.getElementById("prizeRows");
  const add = document.getElementById("addPrizeRow");
  const rowTemplate = document.getElementById("lotteryPrizeRowTemplate");

  if (!rows || !add || !(rowTemplate instanceof HTMLTemplateElement)) {
    return;
  }

  const renumber = () => {
    const prizeRows = rows.querySelectorAll(".lottery-prize-row");
    prizeRows.forEach((row, index) => {
      const indexNode = row.querySelector(".lottery-prize-index");
      if (indexNode) {
        indexNode.textContent = String(index + 1);
      }

      const remove = row.querySelector(".remove-prize");
      if (remove) {
        remove.disabled = prizeRows.length <= 1;
      }
    });
  };

  add.addEventListener("click", () => {
    const fragment = rowTemplate.content.cloneNode(true);
    rows.appendChild(fragment);
    renumber();
  });

  rows.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }

    const button = target.closest(".remove-prize");
    if (!button || rows.querySelectorAll(".lottery-prize-row").length <= 1) {
      return;
    }

    const row = button.closest(".lottery-prize-row");
    if (row) {
      row.remove();
      renumber();
    }
  });

  renumber();
})();
