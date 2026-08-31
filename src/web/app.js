"use strict";
const labels = {purpose:"독립 목적",employment:"고용 상태",education:"학업 상태",current_region:"현재 지역",target_region:"희망 지역",timeline:"독립 시기",housing:"주거 선호",income_status:"독립 후 수입 상태",homeowner:"본인 주택 보유",experience:"자취 경험",property_type:"알아본 건물 유형",priorities:"우선순위 · 복수 선택"};
let options, busy = false;
const statusLine = document.getElementById("status");
function element(tag, text, parent) { const node = document.createElement(tag); node.textContent = text; if(parent) parent.append(node); return node; }
function values() {
  const selections = {}, numbers = {};
  for (const field of document.querySelectorAll("#fields select")) {
    selections[field.name] = field.multiple ? Array.from(field.selectedOptions, o=>o.value) : field.name === "age" ? Number(field.value) : field.value;
  }
  for (const field of document.querySelectorAll('input[type="number"]')) numbers[field.name] = field.value === "" ? null : Number(field.value);
  return {schema_version:"3", selections, numbers};
}
function refresh() {
  const state = document.querySelector('[name="income_status"]').value;
  const income = document.querySelector('[name="monthly_income_krw"]');
  income.disabled = state === "none" || state === "unknown";
  if (income.disabled) income.value = state === "none" ? "0" : "";
  document.getElementById("inputJson").textContent = JSON.stringify(values(), null, 2);
}
function paragraphReport(body, parent) {
  for(const block of body.split(/\n\n+/)) {
    element(block.startsWith("## ") ? "h3" : "p", block.replace(/^## /, "").replace(/\*\*/g,""), parent);
  }
}
function showResult(action, result) {
  const output = document.getElementById("output"); output.replaceChildren();
  if(action === "report") {
    element("h3", result.report.report_title, output); paragraphReport(result.report.report_body_markdown, output);
    element("p", "저장 실행 ID: " + result.run_id, output);
  } else if(action === "policies") {
    element("p", result.notice, output);
    if(!result.policies.length) element("p", "검색 결과가 없습니다. 정책 문서 적재 상태와 선택 조건을 확인하세요.", output);
    for(const policy of result.policies) {
      const card = element("article", "", output); card.className = "policy";
      element("h3", policy.title, card); element("p", policy.application_period, card);
      element("p", policy.notice, card);
      for(const excerpt of policy.excerpts) element("p", `p.${excerpt.page_number} · ${excerpt.content}`, card);
      if(policy.source_url) { try { const url = new URL(policy.source_url); if(["http:","https:"].includes(url.protocol)) { const link = element("a", "원문 확인", card); link.href=url.href;link.target="_blank";link.rel="noopener noreferrer"; } } catch {} }
      element("small", policy.source_file, card);
    }
  } else {
    const names = {complete:"가정 범위 계산 완료",partial:"일부 항목 계산",unavailable:"비용 근거 부족"};
    element("h3", names[result.scope] || result.scope, output);
    element("p", "초기 자금: " + result.initial_status, output);
    element("p", "월 현금흐름: " + result.monthly_status, output);
    const amountLabels = {housing_utilities_capacity_krw:"참고 생활비 차감 후 월 주거·수도·광열 탐색 잔여액",known_initial_cost_krw:"확인된 초기 비용 소계",after_known_initial_cost_krw:"확인된 초기 비용 차감 후 잔액",known_monthly_cost_krw:"계산에 포함한 월 지출 소계",after_known_monthly_cost_krw:"계산에 포함한 월 지출 차감 후 잔액",brokerage_ceiling_excluding_vat_krw:"서울 일반 주택 중개보수 상한 (부가세 별도)"};
    for(const [key,label] of Object.entries(amountLabels)) {
      const b=result.amounts[key]; if(!b) continue;
      const amount=b.lower===b.upper ? b.lower.toLocaleString("ko-KR")+"원" : `${b.lower===null?"하한 미정":b.lower.toLocaleString("ko-KR")+"원"} ~ ${b.upper===null?"상한 미정":b.upper.toLocaleString("ko-KR")+"원"}`;
      element("p",label+": "+amount,output);
    }
    for(const note of result.assumptions) element("p", note, output);
    element("p", "상세 범위와 미확인 항목은 검증용 결과 JSON에서 확인할 수 있습니다.", output);
  }
}
async function execute(action) {
  if(busy || !document.getElementById("situation").reportValidity()) return; busy=true;
  document.querySelectorAll("button[data-action]").forEach(b=>b.disabled=true);
  const input = values();
  document.getElementById("output").replaceChildren();
  document.getElementById("resultJson").textContent="";
  document.querySelectorAll("#situation select, #situation input").forEach(field=>field.disabled=true);
  statusLine.className=""; statusLine.textContent="처리 중입니다. 실제 검색·생성은 시간이 걸릴 수 있습니다.";
  try {
    const response = await fetch("/api/"+action, {method:"POST",headers:{"Content-Type":"application/json","X-CSRF-Token":options.csrf},body:JSON.stringify(input)});
    const result = await response.json();
    if(!response.ok) throw new Error(result.error || "요청 실패");
    document.getElementById("resultJson").textContent=JSON.stringify(result,null,2);
    showResult(action,result); statusLine.textContent="완료했습니다. 실행에 사용한 입력과 결과를 아래에서 확인하세요.";
    document.getElementById("inputJson").textContent=JSON.stringify(input,null,2);
  } catch(error) { statusLine.className="error";statusLine.textContent=error.message; }
  finally {
    busy=false;
    document.querySelectorAll("#situation select, #situation input").forEach(field=>field.disabled=false);
    refresh();
    document.querySelectorAll("button[data-action]").forEach(b=>b.disabled=b.dataset.action!=="calculate"&&!options.external_enabled);
  }
}
async function start() {
  const response=await fetch("/api/options"); if(!response.ok) throw new Error("페이지 설정을 불러오지 못했습니다."); options=await response.json();
  const fields=document.getElementById("fields");
  for(const [name,label] of Object.entries(labels)) {
    const wrap=element("label",label,fields);const select=document.createElement("select");select.name=name;select.id=name;select.multiple=name==="priorities";
    const choices=options.choices[name];
    for(const [code,title] of Object.entries(choices)) { const option=element("option",title,select);option.value=code;option.selected=Array.isArray(options.defaults[name])?options.defaults[name].includes(code):String(options.defaults[name])===String(code); }
    wrap.append(select);
    select.addEventListener("change",()=>{refresh();statusLine.textContent="선택이 변경되었습니다. 기존 결과를 갱신하려면 다시 실행하세요.";});
  }
  document.getElementById("mode").textContent=options.external_enabled?"실제 검색 모드 · 보고서와 정책 검색은 API 사용료가 발생할 수 있습니다. 자동 실행하지 않습니다.":"오프라인 계산 모드 · 실제 검색·생성은 --enable-external로 서버를 실행해야 합니다.";
  for(const button of document.querySelectorAll("button[data-action]")){button.disabled=button.dataset.action!=="calculate"&&!options.external_enabled;button.addEventListener("click",()=>execute(button.dataset.action));}
  const basic=new Set(["age","household_size","available_cash_krw","monthly_income_krw","existing_fixed_cost_krw"]);
  for(const [name,label] of Object.entries(options.number_fields)) {
    const wrap=element("label",label,document.getElementById(basic.has(name)?"numbers":"optionalNumbers"));
    const input=document.createElement("input");input.type="number";input.name=name;input.id=name;input.step="1";input.min=name==="household_size"?"1":"0";input.max=name==="age"?"120":name==="household_size"?"20":"10000000000000";input.inputMode="numeric";
    input.value=options.number_defaults[name]??"";input.required=["age","household_size"].includes(name);input.placeholder="모름은 비워 두세요";
    input.addEventListener("input",()=>{refresh();statusLine.textContent="입력이 변경되었습니다. 결과를 갱신하려면 다시 실행하세요.";});wrap.append(input);
  }
  document.getElementById("situation").addEventListener("submit",event=>event.preventDefault()); refresh();
}
start().catch(error=>{statusLine.className="error";statusLine.textContent=error.message;});
