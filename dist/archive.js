const archiveSearch = document.querySelector("#archive-search");

if (archiveSearch) {
  const cards = [...document.querySelectorAll(".archive-card")];
  const count = document.querySelector("[data-result-count]");
  const empty = document.querySelector(".archive-empty");

  archiveSearch.addEventListener("input", () => {
    const query = archiveSearch.value.trim().toLowerCase();
    let visible = 0;

    cards.forEach((card) => {
      const match = !query || card.dataset.search.includes(query);
      card.hidden = !match;
      if (match) visible += 1;
    });

    if (count) count.textContent = `${visible} result${visible === 1 ? "" : "s"}`;
    if (empty) empty.hidden = visible !== 0;
  });
}
