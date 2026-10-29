"use strict";
const assert = require("node:assert/strict");
const Walkthrough = require("./engine.js");
const scenarios = require("./scenarios.js");
const run = (id) => {
  const flow = new Walkthrough(scenarios.find((scene) => scene.id === id));
  for (const step of flow.scenario.steps) {
    const before = JSON.stringify(flow.state);
    const cursor = flow.cursor;
    assert.equal(flow.execute("无权限角色").ok, false);
    assert.equal(JSON.stringify(flow.state), before);
    assert.equal(flow.cursor, cursor);
    const result = flow.execute(step.actor);
    if (step.denied) assert.equal(JSON.stringify(flow.state), before);
    assert.equal(result.ok, !step.denied);
  }
  return flow.state;
};
assert.equal(new Set(scenarios.map((scene) => scene.id)).size, scenarios.length);
for (const scene of scenarios) run(scene.id);
const sale = new Walkthrough(scenarios.find((scene) => scene.id === "CP-SC-01"));
for (let index = 0; index < 8; index++) sale.execute(sale.scenario.steps[sale.cursor].actor);
assert.equal(sale.state.交付, "仅物主确认");
assert.equal(sale.state.结算, "未发起");
sale.execute("申请人甲");
assert.equal(sale.state.结算, "结算处理中");
assert.equal(run("CP-SC-05").其他申请, "已关闭");
assert.equal(run("CP-SC-06").物品, "已下架");
assert.equal(run("CP-SC-08").借用B, "赔偿结清");
assert.equal(run("CP-SC-08").新增借用, "已自动恢复");
assert.equal(run("CP-SC-11").到账, "未确认");
const loan = new Walkthrough(scenarios.find((scene) => scene.id === "CP-SC-04"));
while (loan.scenario.steps[loan.cursor]?.transition !== "CP-ST-11") {
  loan.execute(loan.scenario.steps[loan.cursor].actor);
}
loan.execute("申请人甲");
assert.equal(loan.state.借用, "待另一方归还确认");
assert.equal(loan.state.押金, "已支付");
loan.execute("物主");
assert.equal(loan.state.借用, "已归还");
assert.equal(loan.state.押金, "退款处理中");
const restoration = new Walkthrough(scenarios.find((scene) => scene.id === "CP-SC-08"));
for (let i = 0; i < 3; i++) {
  restoration.execute(restoration.scenario.steps[restoration.cursor].actor);
  assert.equal(restoration.state.新增借用, "受限");
}
restoration.execute("管理员");
assert.equal(restoration.state.新增借用, "已自动恢复");
const extension = new Walkthrough(scenarios.find((scene) => scene.id === "CP-SC-09"));
extension.execute("申请人甲");
assert.equal(extension.state.有效归还日期, "2026-10-24");
const revision = new Walkthrough(scenarios.find((scene) => scene.id === "DR-SC-04"));
revision.execute("学生G1");
revision.execute("系统事件（模拟）");
revision.execute("系统事件（模拟）");
assert.equal(revision.state.原问题解决, "未确认");
assert.equal(revision.state.v1教师决定, "问题已确认");
assert.equal(run("DR-SC-05").审查结论, "未验证，不能记为没有问题");
console.log(`通过：${scenarios.length} 个预置场景；角色拒绝、状态保持、单方交付、取消、全部恢复、退款及版本保留检查。`);
console.log("范围：只验证原型脚本，不代表真实业务、资金、模型效果或人工走查通过。");
