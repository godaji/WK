/**
 * donate — Supabase Client Module (CMPA-1358)
 * 라이언 딸 심장수술 기부/위스키 판매 문의 페이지.
 * 같은 CaskCode 인프라(dreamjar 와 동일 프로젝트/anon key) 재사용.
 *
 * Usage in index.html:
 *   <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
 *   <script src="./supabase/supabase.js"></script>
 *   <script src="./app.js"></script>
 */
(() => {
  'use strict';

  const SUPABASE_URL      = 'https://odtivpszffoufyiufqwy.supabase.co';
  const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9kdGl2cHN6ZmZvdWZ5aXVmcXd5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODM2ODkzMTYsImV4cCI6MjA5OTI2NTMxNn0.XrXsMLtRCUbAJvFdWz_JMZ3VwFWwGBsP2YqQ0NO7m7I';

  const supabase = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

  const LESSON_THRESHOLD = 300000; // 30만원 이상 → 원포인트 레슨

  /**
   * 위스키 구매 문의를 저장한다.
   * @param {{whiskies:{name:string,qty:number}[], amount:number,
   *          depositorName:string, shippingAddress:string, contact?:string}} p
   * RLS: anon insert 만 허용(select 불가) → .select() 를 붙이지 않는다.
   */
  async function submitInquiry(p) {
    const amount = Math.max(0, Math.floor(Number(p.amount) || 0));
    const row = {
      whiskies: Array.isArray(p.whiskies) ? p.whiskies : [],
      amount,
      depositor_name: (p.depositorName || '').trim(),
      shipping_address: (p.shippingAddress || '').trim(),
      contact: (p.contact || '').trim() || null,
      one_point_lesson: amount >= LESSON_THRESHOLD,
    };
    const { error } = await supabase.from('whisky_inquiries').insert(row);
    if (error) throw error;
    return { ok: true, onePointLesson: row.one_point_lesson };
  }

  window.DonateSupabase = {
    submitInquiry,
    LESSON_THRESHOLD,
  };
})();
