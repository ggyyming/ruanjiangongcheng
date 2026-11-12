"use strict";
const roles = ["访客", "未认证用户", "物主", "申请人甲", "申请人乙", "管理员", "学生G1", "学生G2", "教师G1", "教师G2", "系统事件（模拟）", "第三方事件（模拟）"];
const $ = (id) => document.getElementById(id);
let currentSystem = "cp";
let walkthrough;
let attempts = [];
function textElement(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}
function selectScenario(id) {
  walkthrough = new Walkthrough(DEMO_SCENARIOS.find((scene) => scene.id === id));
  attempts = [];
  $("actor").value = "访客";
  $("feedback").className = "";
  $("feedback").textContent = "请选择角色并执行；选择其他角色可检查权限拒绝。";
  render();
}
function render() {
  const scene = walkthrough.scenario;
  $("scenarios").replaceChildren();
  for (const candidate of DEMO_SCENARIOS.filter((item) => item.system === currentSystem)) {
    const button = textElement("button", candidate.title, `scenario${candidate.id === scene.id ? " active" : ""}`);
    button.append(textElement("small", candidate.id));
    button.onclick = () => selectScenario(candidate.id);
    $("scenarios").append(button);
  }
  $("scene-id").textContent = scene.id;
  $("title").textContent = scene.title;
  $("intro").textContent = scene.intro;
  $("type").textContent = scene.type;
  $("rules").textContent = `关联规则：${scene.rules}`;
  $("state").replaceChildren();
  for (const [key, value] of Object.entries(walkthrough.state)) {
    const card = textElement("div", "", "state-card");
    card.append(textElement("small", key), textElement("strong", value));
    $("state").append(card);
  }
  $("document-panel").hidden = !scene.document;
  $("document").textContent = scene.document ? scene.document.split("\n").map((line, index) => `${index + 1}  ${line}`).join("\n") : "";
  const next = scene.steps[walkthrough.cursor];
  $("progress").textContent = `已演示 ${walkthrough.cursor} / ${scene.steps.length} 步；所有结果均为脚本模拟。`;
  $("execute").disabled = !next;
  $("execute").textContent = next ? next.action : "本场景已结束";
  $("expected-role").textContent = next ? `步骤所需角色：${next.actor} · 转换记录：${next.transition}` : "可重置本场景，或选择其他场景。";
  $("steps").replaceChildren();
  scene.steps.forEach((item, index) => {
    const li = textElement("li", `${item.actor}：${item.action}`, index < walkthrough.cursor ? "done" : index === walkthrough.cursor ? "current" : "");
    li.append(textElement("small", `${item.transition} · ${item.result}`));
    $("steps").append(li);
  });
  $("log").replaceChildren();
  for (const attempt of attempts) {
    const entry = textElement("div", "", "log-entry");
    entry.append(textElement("strong", `${attempt.actor} · ${attempt.action}`), textElement("div", attempt.message), textElement("small", attempt.time));
    $("log").prepend(entry);
  }
}
for (const role of roles) $("actor").append(textElement("option", role));
$("execute").onclick = () => {
  const next = walkthrough.scenario.steps[walkthrough.cursor];
  const actor = $("actor").value;
  const result = walkthrough.execute(actor);
  attempts.push({ actor, action: next.action, message: result.message, time: new Date().toISOString(), state: { ...walkthrough.state } });
  $("feedback").textContent = result.message;
  $("feedback").className = result.ok ? "success" : "error";
  render();
};
$("reset").onclick = () => selectScenario(walkthrough.scenario.id);
for (const button of document.querySelectorAll("[data-system]")) {
  button.onclick = () => {
    currentSystem = button.dataset.system;
    document.querySelectorAll("[data-system]").forEach((tab) => tab.classList.toggle("active", tab === button));
    selectScenario(DEMO_SCENARIOS.find((scene) => scene.system === currentSystem).id);
  };
}
$("download").onclick = () => {
  const record = {
    prototype: "双主题可点击模拟原型 v0.1", scenario: walkthrough.scenario.id,
    scope: "仅前端脚本模拟；未接真实支付或模型；未实现服务端授权；人工结论由实际走查者填写",
    completedSteps: walkthrough.cursor, observations: attempts
  };
  const url = URL.createObjectURL(new Blob([JSON.stringify(record, null, 2)], { type: "application/json;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${walkthrough.scenario.id}-点击记录.json`;
  link.click();
  URL.revokeObjectURL(url);
};
selectScenario("CP-SC-01");
