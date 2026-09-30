"use strict";

const $ = (id) => document.getElementById(id);

const fields = [
  "probeA", "probeB", "offsetMin", "offsetMax", "tolerance", "minPairs",
  "gapLimitEnabled", "maxSkippedA", "maxSkippedB",
];

function gapLimitOn() {
  return $("gapLimitEnabled").checked;
}

function syncGapInputs() {
  $("gapLimitInputs").hidden = !gapLimitOn();
}

function markStale() {
  // 旧结论立即失效：隐藏上一次结果，避免被误读为当前输入的结论。
  $("staleNote").hidden = false;
  $("resultPanel").hidden = true;
  $("errorBox").hidden = true;
}

fields.forEach((id) => {
  $(id).addEventListener("input", markStale);
});
$("gapLimitEnabled").addEventListener("change", () => {
  syncGapInputs();
  markStale();
});
syncGapInputs();

function parseTimes(text) {
  return text
    .split(/[\s,;]+/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

function showError(message) {
  const box = $("errorBox");
  box.textContent = message;
  box.hidden = false;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function metric(key, value, diagnostic = false) {
  return `<div class="metric${diagnostic ? " diagnostic" : ""}">
    <span class="k">${key}</span><span class="v">${value}</span></div>`;
}

function renderSegments(view, limits, opts = {}) {
  // view: {segments:[...], breaks:[...]} from the API (answer or fracture).
  const title = opts.title || "连续漏失分段（相邻符合事件之间两侧跳过的脉冲数）";
  const note = opts.note || "";
  const la = limits.max_skipped_a;
  const lb = limits.max_skipped_b;

  const segCards = view.segments.map((s) => {
    const gapRows = s.gaps.length
      ? s.gaps.map((g) => `<tr>
          <td>A#${g.after_index_a}→A#${g.before_index_a}</td>
          <td>B#${g.after_index_b}→B#${g.before_index_b}</td>
          <td class="${g.a_within_limit ? "gap-ok" : "gap-bad"}">
            ${g.skipped_a}${g.a_within_limit ? "" : " ✕"}</td>
          <td class="${g.b_within_limit ? "gap-ok" : "gap-bad"}">
            ${g.skipped_b}${g.b_within_limit ? "" : " ✕"}</td>
        </tr>`).join("")
      : `<tr><td colspan="4" class="empty-note">段内无相邻配对间隔（仅一对）。</td></tr>`;
    return `<div class="segment-card">
      <h4>第 ${s.segment} 段：${s.pair_count} 对
        （A#${s.first_index_a}–A#${s.last_index_a}，
         B#${s.first_index_b}–B#${s.last_index_b}）</h4>
      <table>
        <thead><tr><th>相邻符合事件（A）</th><th>相邻符合事件（B）</th>
        <th>A 侧跳过（≤${la}）</th><th>B 侧跳过（≤${lb}）</th></tr></thead>
        <tbody>${gapRows}</tbody>
      </table>
      <p class="empty-note">段内两侧漏失合计：A 侧 ${s.internal_skipped_a} 个，
        B 侧 ${s.internal_skipped_b} 个；首对之前、末对之后不计入。</p>
    </div>`;
  }).join("");

  const breakRows = view.breaks.length
    ? view.breaks.map((b) => {
        const g = b;
        const why = [];
        if (!g.a_within_limit) why.push(`A 侧跳过 ${g.skipped_a} 个 &gt; ${la}`);
        if (!g.b_within_limit) why.push(`B 侧跳过 ${g.skipped_b} 个 &gt; ${lb}`);
        return `<tr>
          <td>第 ${b.after_segment} 段 → 第 ${b.before_segment} 段</td>
          <td>A#${g.after_index_a}→A#${g.before_index_a}</td>
          <td>B#${g.after_index_b}→B#${g.before_index_b}</td>
          <td class="gap-bad">${g.skipped_a}${g.a_within_limit ? "" : " ✕"}</td>
          <td class="gap-bad">${g.skipped_b}${g.b_within_limit ? "" : " ✕"}</td>
          <td>${why.join("；")}</td>
        </tr>`;
      }).join("")
    : "";
  const breakTable = view.breaks.length
    ? `<h4>造成断裂的漏失区段</h4>
       <table>
         <thead><tr><th>断裂位置</th><th>间隔（A）</th><th>间隔（B）</th>
         <th>A 侧跳过</th><th>B 侧跳过</th><th>越限说明</th></tr></thead>
         <tbody>${breakRows}</tbody>
       </table>`
    : "";

  return `<h3>${esc(title)}</h3>${note}${segCards}${breakTable}`;
}

function renderPairs(pairs, showSegment) {
  if (!pairs.length) {
    return `<h3>配对明细</h3><p class="empty-note">没有任何满足容差的配对。</p>`;
  }
  const segHead = showSegment ? "<th>段</th>" : "";
  const rows = pairs.map((p) => {
    const cls = p.residual > 0 ? "res-pos" : p.residual < 0 ? "res-neg" : "res-zero";
    const sign = p.residual > 0 ? "+" : "";
    const segCell = showSegment ? `<td>${p.segment ?? ""}</td>` : "";
    return `<tr>
      <td>#${p.index_a}</td><td>#${p.index_b}</td>${segCell}
      <td>${p.a_time}</td><td>${p.corrected_b}</td>
      <td class="${cls}">${sign}${p.residual}</td>
    </tr>`;
  }).join("");
  const segTh = showSegment ? "<th>段</th>" : "";
  return `<h3>配对明细（校正时间 = B 时间 + 偏移；带符号残差 = A − 校正后 B）</h3>
    <table>
      <thead><tr><th>A 序号</th><th>B 序号</th>${segTh}
      <th>A 时间 (ns)</th><th>B 校正时间 (ns)</th><th>残差 (ns)</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderUnpaired(title, list) {
  if (!list.length) {
    return `<h3>${title}</h3><p class="empty-note">无未配对脉冲。</p>`;
  }
  const chips = list
    .map((u) => `<span class="chip"><b>#${u.index}</b>${u.time}</span>`)
    .join("");
  return `<h3>${title}</h3><div class="chips">${chips}</div>`;
}

function renderResult(r) {
  const panel = $("resultPanel");
  panel.hidden = false;
  const capped = !!(r.gap_limits && r.gap_limits.enabled);
  const limits = capped
    ? r.gap_limits
    : { max_skipped_a: null, max_skipped_b: null };
  const capDesc = capped
    ? `（连续漏失上限：A 侧 ${limits.max_skipped_a} 个、B 侧 ${limits.max_skipped_b} 个）`
    : "";

  let segmentsHtml = "";
  if (r.sufficient) {
    $("verdict").innerHTML =
      `<div class="verdict ok">校准成立：最佳整数时钟偏移为
        <span style="font-variant-numeric:tabular-nums">${r.offset}</span> ns，
        形成 ${r.pair_count} 对符合事件（门槛 ${r.min_pairs} 对）${capDesc}。</div>`;
    $("metrics").innerHTML =
      metric("最佳整数偏移 (ns)", r.offset) +
      metric("配对数", `${r.pair_count} / 门槛 ${r.min_pairs}`) +
      metric("残差绝对值总和 (ns)", r.residual_abs_sum) +
      metric("最大残差绝对值 (ns)", r.max_abs_residual);
    if (capped) {
      segmentsHtml = renderSegments(
        { segments: r.segments, breaks: r.breaks }, limits
      );
    }
  } else {
    // 不伪造校准值：不把任何偏移作为校准结论展示。
    $("verdict").innerHTML =
      `<div class="verdict bad">无法形成足够的符合事件${capDesc}：
        约束下实际最大配对数为
        <span style="font-variant-numeric:tabular-nums">${r.pair_count}</span>
        对，低于最低配对数 ${r.min_pairs} 对。
        <span class="reason">${esc(r.reason || "")}</span></div>`;
    $("metrics").innerHTML =
      metric("约束下实际最大配对数", `${r.pair_count} / 门槛 ${r.min_pairs}`) +
      metric("残差绝对值总和 (ns)", r.residual_abs_sum) +
      metric("最大残差绝对值 (ns)", r.max_abs_residual);
    if (capped) {
      const diag = r.diagnostic || {};
      // 约束答案的逐段漏失数。
      const answerSeg = renderSegments(
        {
          segments: diag.segments || [],
          breaks: [],
        },
        limits,
        {
          title: "约束下最大配对方案的连续漏失分段",
          note: `<p class="diagnostic-note">该方案的每个相邻间隔均满足两侧上限，
            故为一整段；首对之前、末对之后不计入。</p>`,
        },
      );
      // 造成断裂的漏失区段：不受限最优对齐被上限切开的位置。
      const frac = diag.fracture;
      const fractureSeg = frac
        ? renderSegments(frac, limits, {
            title: "造成断裂的漏失区段（不受限最优对齐按上限切分，仅诊断）",
            note: `<p class="diagnostic-note">不启用上限时最多可配
              ${frac.pair_count} 对；按连续漏失上限切分后，下表列出使其无法
              连成一次校准的断裂间隔。</p>`,
          })
        : `<p class="diagnostic-note">不存在可在容差内配成的更长对齐，
            因而没有断裂区段。</p>`;
      segmentsHtml = answerSeg + fractureSeg;
    }
  }
  $("segmentsWrap").innerHTML = segmentsHtml;

  $("pairsWrap").innerHTML = r.sufficient
    ? renderPairs(r.pairs, capped)
    : `<p class="diagnostic-note">以下为约束下最大配对数（${r.pair_count} 对）的
        对齐明细，仅用于诊断，不构成校准结论，页面不给出校准偏移。</p>` +
      renderPairs((r.diagnostic && r.diagnostic.pairs) || [], capped);
  $("unpairedA").innerHTML = renderUnpaired("未配对的 A 脉冲（序号 / 时间）", r.unpaired_a);
  $("unpairedB").innerHTML = renderUnpaired("未配对的 B 脉冲（序号 / 时间）", r.unpaired_b);
}

async function submit() {
  const payload = {
    probe_a: parseTimes($("probeA").value),
    probe_b: parseTimes($("probeB").value),
    offset_min: $("offsetMin").value.trim(),
    offset_max: $("offsetMax").value.trim(),
    tolerance: $("tolerance").value.trim(),
    min_pairs: $("minPairs").value.trim(),
    gap_limit_enabled: gapLimitOn(),
  };
  if (gapLimitOn()) {
    payload.max_skipped_a = $("maxSkippedA").value.trim();
    payload.max_skipped_b = $("maxSkippedB").value.trim();
  }

  const btn = $("submitBtn");
  btn.disabled = true;
  const oldHtml = btn.innerHTML;
  btn.innerHTML = `<span class="spinner"></span>计算中…`;
  try {
    const resp = await fetch("/api/calibrate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    let data;
    try {
      data = await resp.json();
    } catch (e) {
      throw new Error("服务返回了无法解析的响应");
    }
    if (!resp.ok) {
      showError(data.error || `请求失败（HTTP ${resp.status}）`);
      return;
    }
    renderResult(data);
    $("staleNote").hidden = true;
  } catch (err) {
    showError(`提交失败：${err.message}`);
  } finally {
    btn.disabled = false;
    btn.innerHTML = oldHtml;
  }
}

$("submitBtn").addEventListener("click", submit);
