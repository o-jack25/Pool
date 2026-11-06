(() => {
  const flashCloseButtons = document.querySelectorAll('.flash-close');
  flashCloseButtons.forEach((button) => {
    button.addEventListener('click', () => button.closest('.flash')?.remove());
  });

  const scoreForm = document.querySelector('[data-score-form]');
  if (!scoreForm) return;

  const subToggle = scoreForm.querySelector('[data-sub-toggle]');
  const subNameWrap = scoreForm.querySelector('[data-sub-name-wrap]');
  const subName = scoreForm.querySelector('[data-sub-name]');
  const balls = scoreForm.querySelector('[data-balls]');
  const eightBall = scoreForm.querySelector('[data-eight]');
  const points = scoreForm.querySelector('[data-points]');
  const equation = scoreForm.querySelector('[data-equation]');

  const updateScore = () => {
    const ballCount = Number.parseInt(balls.value, 10) || 0;
    const canMakeEight = ballCount === 7;
    eightBall.disabled = !canMakeEight;
    if (!canMakeEight) eightBall.checked = false;

    const total = ballCount + (eightBall.checked ? 3 : 0);
    points.innerHTML = `${total} <small>PTS</small>`;
    equation.textContent = eightBall.checked
      ? '7 object balls + 3-point 8-ball bonus'
      : `${ballCount} ${ballCount === 1 ? 'ball' : 'balls'} × 1 point${canMakeEight ? ' · 8-ball adds 3' : ''}`;
  };

  subToggle.addEventListener('change', () => {
    subNameWrap.hidden = !subToggle.checked;
    subName.required = subToggle.checked;
    if (!subToggle.checked) subName.value = '';
  });
  balls.addEventListener('change', updateScore);
  eightBall.addEventListener('change', updateScore);
  updateScore();
})();
