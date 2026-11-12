(function (root) {
  "use strict";
  class Walkthrough {
    constructor(scenario) {
      this.scenario = scenario;
      this.state = { ...scenario.initial };
      this.cursor = 0;
      this.log = [];
    }
    execute(actor) {
      const step = this.scenario.steps[this.cursor];
      if (!step) return { ok: false, message: "本场景已结束，可重置或切换场景。" };
      if (actor !== step.actor) {
        return { ok: false, message: `操作被拒绝：本步骤需要${step.actor}；业务数据和步骤均保持。` };
      }
      const before = { ...this.state };
      Object.assign(this.state, step.patch || {});
      this.cursor += 1;
      const result = { ok: !step.denied, message: step.result, before, after: { ...this.state }, step };
      this.log.push(result);
      return result;
    }
  }
  if (typeof module !== "undefined") module.exports = Walkthrough;
  else root.Walkthrough = Walkthrough;
})(globalThis);
