/**
 * donate — 위스키 구매 문의 폼 로직 (CMPA-1358)
 * 라인 아이템(위스키명+수량) 추가/삭제, 금액 30만원 이상 레슨 뱃지,
 * Supabase 저장, 계좌 복사.
 */
(() => {
  'use strict';

  const $  = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const LESSON_THRESHOLD =
    (window.DonateSupabase && window.DonateSupabase.LESSON_THRESHOLD) || 300000;

  // ── 라인 아이템(위스키명 + 수량) ──────────────────────────
  const itemList = $('#itemList');

  function addItem(name = '', qty = 1) {
    const row = document.createElement('div');
    row.className = 'item-row';
    row.innerHTML = `
      <input class="input item-name" type="text" placeholder="위스키명 (예: 발베니 12년)" maxlength="80">
      <input class="input item-qty" type="text" inputmode="numeric" placeholder="수량" aria-label="수량">
      <button type="button" class="item-del" aria-label="이 줄 삭제">✕</button>`;
    row.querySelector('.item-name').value = name;
    row.querySelector('.item-qty').value = qty;
    row.querySelector('.item-del').addEventListener('click', () => {
      row.remove();
      if (!itemList.children.length) addItem();
    });
    itemList.appendChild(row);
  }

  function readItems() {
    return $$('.item-row', itemList)
      .map((row) => {
        const name = row.querySelector('.item-name').value.trim();
        const qty = Math.max(1, parseInt(row.querySelector('.item-qty').value, 10) || 1);
        return { name, qty };
      })
      .filter((it) => it.name);
  }

  $('#addItemBtn').addEventListener('click', () => addItem());
  addItem(); // 초기 한 줄

  // ── 금액 입력: 천단위 콤마 + 레슨 뱃지 ────────────────────
  const amountInput = $('#amount');
  const lessonBadge = $('#lessonBadge');

  function parseAmount(str) {
    return parseInt(String(str).replace(/[^\d]/g, ''), 10) || 0;
  }

  amountInput.addEventListener('input', () => {
    const n = parseAmount(amountInput.value);
    amountInput.value = n ? n.toLocaleString('ko-KR') : '';
    lessonBadge.hidden = n < LESSON_THRESHOLD;
  });

  // ── 계좌 복사 ─────────────────────────────────────────────
  const copyBtn = $('#copyBtn');
  copyBtn.addEventListener('click', async () => {
    const num = $('#accountNum').textContent.trim();
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(num);
      } else {
        const ta = document.createElement('textarea');
        ta.value = num;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }
      const prev = copyBtn.textContent;
      copyBtn.textContent = '복사됨';
      copyBtn.classList.add('copied');
      setTimeout(() => {
        copyBtn.textContent = prev;
        copyBtn.classList.remove('copied');
      }, 1500);
    } catch (e) {
      copyBtn.textContent = '복사 실패';
      setTimeout(() => (copyBtn.textContent = '복사'), 1500);
    }
  });

  // ── 폼 제출 ───────────────────────────────────────────────
  const form = $('#inquiryForm');
  const formError = $('#formError');
  const submitBtn = $('#submitBtn');
  const thanks = $('#thanks');
  const formCardForm = form;

  function showError(msg) {
    formError.textContent = msg;
    formError.hidden = false;
  }

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    formError.hidden = true;

    const whiskies = readItems();
    const amount = parseAmount(amountInput.value);
    const depositorName = $('#depositor').value.trim();
    const shippingAddress = $('#address').value.trim();
    const contact = $('#contact').value.trim();

    if (!whiskies.length) return showError('구매하실 위스키를 한 개 이상 적어주세요.');
    if (!amount)          return showError('입금 예정 금액을 입력해주세요.');
    if (!depositorName)   return showError('입금자 이름을 입력해주세요.');
    if (!shippingAddress) return showError('배송지 주소를 입력해주세요.');

    submitBtn.disabled = true;
    submitBtn.textContent = '보내는 중…';
    try {
      const res = await window.DonateSupabase.submitInquiry({
        whiskies, amount, depositorName, shippingAddress, contact,
      });
      formCardForm.hidden = true;
      thanks.hidden = false;
      $('#thanksLesson').hidden = !res.onePointLesson;
      thanks.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (e) {
      showError('전송 중 문제가 생겼습니다. 잠시 후 다시 시도해주세요.');
      submitBtn.disabled = false;
      submitBtn.textContent = '문의 보내기';
    }
  });

  // 다른 문의 남기기 → 폼 초기화
  $('#againBtn').addEventListener('click', () => {
    form.reset();
    itemList.innerHTML = '';
    addItem();
    lessonBadge.hidden = true;
    submitBtn.disabled = false;
    submitBtn.textContent = '문의 보내기';
    thanks.hidden = true;
    formCardForm.hidden = false;
    $('#formCard').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
})();
