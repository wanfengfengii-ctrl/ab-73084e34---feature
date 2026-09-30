"use strict";

const $ = (id) => document.getElementById(id);

const fields = [
  "probeA", "probeB", "offsetMin", "offsetMax", "tolerance", "minPairs",
  "gapLimitEnabled", "maxGapA", "maxGapB",
];

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
  $("gapFields").hidden = !$("gapLimitEnabled").checked;
  markStale();
});

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

function renderPairs(pairs) {
  if (!pairs.length) {
    return `<h3>配对明细</h3><p class="empty-note">没有任何满足容差的配对。</p>`;
  }
  const rows = pairs.map((p) => {
    const cls = p.residual > 0 ? "res-pos" : p.residual < 0 ? "res-neg" : "res-zero";
    const sign = p.residual > 0 ? "+" : "";
    return `<tr>
      <td>#${p.index_a}</td><td>#${p.index_b}</td>
      <td>${p.a_time}</td><td>${p.corrected_b}</td>
      <td class="${cls}">${sign}${p.residual}</td>
    </tr>`;
  }).join("");
  return `<h3>配对明细（校正时间 = B 时间 + 偏移；带符号残差 = A − 校正后 B）</h3>
    <table>
      <thead><tr><th>A 序号</th><th>B 序号</th><th>A 时间 (ns)</th>
      <th>B 校正时间 (ns)</th><th>残差 (ns)</th></tr></thead>
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

function renderGapSegments(r, segments, title, note, emptyText) {
  if (!r.gap_limit_enabled) return "";
  if (segments.length === 0) {
    return `<h3>${title}</h3>
      <p class="empty-note">${emptyText
        || "配对数少于 2 对，无相邻配对之间的漏失区段"
        + "（首对之前与末对之后的脉冲不计入约束）。"}</p>`;
  }
  const rows = segments.map((g) => {
    const breachA = g.skipped_a > r.max_gap_a;
    const breachB = g.skipped_b > r.max_gap_b;
    const cls = (breachA || breachB) ? "gap-breach" : "";
    const mark = (v, b) => b ? `<span class="breach">${v} ✕</span>` : v;
    return `<tr class="${cls}">
      <td>第 ${g.after_pair} 对 → 第 ${g.after_pair + 1} 对</td>
      <td class="${breachA ? "res-neg" : ""}">${mark(g.skipped_a, breachA)}</td>
      <td class="${breachB ? "res-neg" : ""}">${mark(g.skipped_b, breachB)}</td>
      <td>${g.a_indices.map((i) => "#" + i).join(" ") || "—"}</td>
      <td>${g.b_indices.map((i) => "#" + i).join(" ") || "—"}</td>
    </tr>`;
  }).join("");
  return `<h3>${title}</h3>
    ${note ? `<p class="diagnostic-note">${note}</p>` : ""}
    <table>
      <thead><tr><th>相邻符合事件</th><th>A 侧跳过脉冲数（上限 ${r.max_gap_a}）</th>
      <th>B 侧跳过脉冲数（上限 ${r.max_gap_b}）</th><th>A 侧跳过序号</th>
      <th>B 侧跳过序号</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderResult(r) {
  const panel = $("resultPanel");
  panel.hidden = false;

  const gapOn = !!r.gap_limit_enabled;
  const gapDesc = gapOn
    ? `（连续漏失上限：A 侧 ${r.max_gap_a}、B 侧 ${r.max_gap_b}）`
    : "";

  if (r.sufficient) {
    $("verdict").innerHTML =
      `<div class="verdict ok">校准成立：最佳整数时钟偏移为
        <span style="font-variant-numeric:tabular-nums">${r.offset}</span> ns，
        形成 ${r.pair_count} 对符合事件（门槛 ${r.min_pairs} 对）${gapDesc}。</div>`;
    $("metrics").innerHTML =
      metric("最佳整数偏移 (ns)", r.offset) +
      metric("配对数", `${r.pair_count} / 门槛 ${r.min_pairs}`) +
      metric("残差绝对值总和 (ns)", r.residual_abs_sum) +
      metric("最大残差绝对值 (ns)", r.max_abs_residual);
  } else {
    // 不伪造校准值：不把任何偏移作为校准结论展示。
    const gapReason = gapOn
      ? `启用连续漏失上限（A 侧 ${r.max_gap_a}、B 侧 ${r.max_gap_b}）后，`
        + `满足约束的实际最大配对数仅为 ${r.pair_count} 对，低于门槛 ${r.min_pairs} 对。`
      : `实际最大配对数为 <span style="font-variant-numeric:tabular-nums">${r.pair_count}</span>
        对，低于最低配对数 ${r.min_pairs} 对。`;
    $("verdict").innerHTML =
      `<div class="verdict bad">无法形成足够的符合事件：${gapReason}
        <span class="reason">${esc(r.reason || "")}</span></div>`;
    $("metrics").innerHTML =
      metric("实际最大配对数", `${r.pair_count} / 门槛 ${r.min_pairs}`) +
      metric("残差绝对值总和 (ns)", r.residual_abs_sum) +
      metric("最大残差绝对值 (ns)", r.max_abs_residual);
  }

  const diagPairs = (r.diagnostic && r.diagnostic.pairs) || [];
  const shownPairs = r.sufficient ? r.pairs : diagPairs;
  if (r.sufficient) {
    $("gapWrap").innerHTML = renderGapSegments(
      r, r.gap_segments,
      "逐段漏失统计（相邻两对符合事件之间跳过的脉冲数）",
      "首对之前与末对之后的脉冲不计入连续漏失约束。",
    );
  } else if (gapOn) {
    $("gapWrap").innerHTML =
      renderGapSegments(
        r, r.broken_segments || [],
        "造成断裂的漏失区段（无约束最优配对中越过上限的位置）",
        "下列区段中至少一侧跳过脉冲数越限，联合求解时符合链必须在此断开。",
        "无约束最优配对本身不存在越过漏失上限的相邻区段。",
      )
      + renderGapSegments(
        r, (r.diagnostic && r.diagnostic.gap_segments) || [],
        "约束下实际最大配对数方案的逐段漏失（诊断）",
        "该方案满足全部连续漏失约束，但配对数低于门槛，不构成校准结论。",
        "该方案配对数少于 2 对，无相邻配对之间的漏失区段。",
      );
  } else {
    $("gapWrap").innerHTML = "";
  }
  $("pairsWrap").innerHTML = r.sufficient
    ? renderPairs(r.pairs)
    : `<p class="diagnostic-note">以下为最大配对数（${r.pair_count} 对）的对齐明细，
        仅用于诊断，不构成校准结论，页面不给出校准偏移。</p>` +
      renderPairs(shownPairs);
  $("unpairedA").innerHTML = renderUnpaired("未配对的 A 脉冲（序号 / 时间）", r.unpaired_a);
  $("unpairedB").innerHTML = renderUnpaired("未配对的 B 脉冲（序号 / 时间）", r.unpaired_b);
}

async function submit() {
  const gapEnabled = $("gapLimitEnabled").checked;
  const payload = {
    probe_a: parseTimes($("probeA").value),
    probe_b: parseTimes($("probeB").value),
    offset_min: $("offsetMin").value.trim(),
    offset_max: $("offsetMax").value.trim(),
    tolerance: $("tolerance").value.trim(),
    min_pairs: $("minPairs").value.trim(),
    gap_limit_enabled: gapEnabled,
  };
  if (gapEnabled) {
    payload.max_gap_a = $("maxGapA").value.trim();
    payload.max_gap_b = $("maxGapB").value.trim();
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
