"use strict";
const roles = ["访客", "未认证用户", "物主", "申请人甲", "申请人乙", "管理员", "学生G1", "学生G2", "学生G3", "学生G4", "教师T1", "教师T2", "系统事件（模拟）", "第三方事件（模拟）"];
const $ = (id) => document.getElementById(id);
let currentSystem = "cp";
let walkthrough;
let attempts = [];
let classroom = new ClassroomDemo();
let selectedClass = "";
let selectedWork = null;
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
  $("classroom-actor").value = "访客";
  selectedWork = null;
  $("feedback").className = "";
  $("feedback").textContent = "请选择角色并执行；选择其他角色可检查权限拒绝。";
  render();
}
function render() {
  const scene = walkthrough.scenario;
  renderClassroom();
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
function renderClassroom() {
  $("classroom-panel").hidden = currentSystem !== "dr";
  const actor = $("actor").value;
  const classes = classroom.classesFor(actor);
  if (!classes.some((item) => item.id === selectedClass)) selectedClass = classes[0]?.id || "";
  $("classroom-select").replaceChildren();
  for (const item of classes) {
    const option = textElement("option", `${item.course} · ${item.term} · ${item.name}（${item.id}）`);
    option.value = item.id;
    $("classroom-select").append(option);
  }
  $("classroom-select").value = selectedClass;
  $("classroom-rows").replaceChildren();
  $("work-detail").replaceChildren();
  if (!selectedClass) {
    $("classroom-feedback").textContent = "请选择教师T1/教师T2或学生G1～G4。教师T1负责C1，教师T2负责C2；均为虚构示例。";
    return;
  }
  const teacher = classroom.isTeacher(actor, selectedClass);
  const rows = teacher ? classroom.rows(actor, selectedClass) : classroom.ownWorks(actor, selectedClass).map((work) => ({ groupId: work.groupId, submitted: true, workId: work.id, title: work.title, version: work.version, pending: work.issues.filter((issue) => issue.status === "待教师复核" || issue.status === "待核实").length }));
  $("classroom-feedback").textContent = teacher ? "当前显示本教学班全部小组：未提交组也保留一行；打开不同组作品可分别复核。" : "学生只显示本组已提交作品；没有作品时表示本组尚未提交。";
  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const value of [row.groupId, row.title, row.version, row.pending ?? "—"]) tr.append(textElement("td", String(value)));
    const td = document.createElement("td");
    const button = textElement("button", teacher ? "查看并复核" : "查看本组作品");
    button.disabled = !row.submitted;
    button.onclick = () => { selectedWork = row.workId; renderClassroom(); };
    td.append(button);
    tr.append(td);
    $("classroom-rows").append(tr);
  }
  if (!selectedWork) return;
  try {
    const work = classroom.work(actor, selectedWork);
    if (work.classId !== selectedClass) { selectedWork = null; return; }
    const detail = $("work-detail");
    detail.append(textElement("h3", `${work.title} · ${work.classId}/${work.groupId}/${work.version}`), textElement("pre", `1  ${work.text}`));
    for (const issue of work.issues) {
      const card = textElement("div", "", "work-issue");
      card.append(textElement("strong", `${issue.type} · ${issue.location} · ${issue.status}`), textElement("p", issue.note ? `模拟复核理由：${issue.note}` : "尚无模拟复核理由；本候选为预置示例。"));
      if (teacher) {
        const label = textElement("label", "本次模拟复核理由");
        const note = document.createElement("textarea");
        note.rows = 2;
        label.append(note);
        const controls = textElement("div", "", "controls");
        for (const decision of ["已确认", "已驳回", "待核实"]) {
          const button = textElement("button", decision);
          button.onclick = () => {
            try { classroom.decide(actor, work.id, issue.id, decision, note.value); renderClassroom(); }
            catch (error) { $("classroom-feedback").textContent = error.message; }
          };
          controls.append(button);
        }
        card.append(label, controls);
      }
      detail.append(card);
    }
    detail.append(textElement("p", "以上仅为本次内存模拟；其他组的记录独立，刷新或重置会清空，未保存到后台。"));
  } catch (error) { selectedWork = null; $("classroom-feedback").textContent = error.message; }
}
for (const role of roles) {
  $("actor").append(textElement("option", role));
  $("classroom-actor").append(textElement("option", role));
}
$("actor").onchange = () => { $("classroom-actor").value = $("actor").value; selectedWork = null; renderClassroom(); };
$("classroom-actor").onchange = () => { $("actor").value = $("classroom-actor").value; selectedWork = null; renderClassroom(); };
$("classroom-select").onchange = () => { selectedClass = $("classroom-select").value; selectedWork = null; renderClassroom(); };
$("classroom-reset").onclick = () => { classroom = new ClassroomDemo(); selectedWork = null; renderClassroom(); };
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
    prototype: "双主题可点击模拟原型 v0.2", scenario: walkthrough.scenario.id,
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
