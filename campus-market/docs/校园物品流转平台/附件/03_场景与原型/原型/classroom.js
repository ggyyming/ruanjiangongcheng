(function (root) {
  "use strict";
  const initial = {
    classes: [
      { id: "C1", course: "软件工程", term: "2026秋（示例）", name: "教学1班", teacher: "教师T1" },
      { id: "C2", course: "软件工程", term: "2026秋（示例）", name: "教学2班", teacher: "教师T2" }
    ],
    groups: [
      { id: "G1", classId: "C1", members: ["学生G1"] },
      { id: "G2", classId: "C1", members: ["学生G2"] },
      { id: "G3", classId: "C1", members: ["学生G3"] },
      { id: "G4", classId: "C2", members: ["学生G4"] }
    ],
    works: [
      { id: "W1", classId: "C1", groupId: "G1", title: "G1 需求规格说明书", version: "v1", text: "系统应尽快返回结果。", issues: [{ id: "I1", type: "模糊表述", location: "第1行", status: "待教师复核", note: "" }] },
      { id: "W2", classId: "C1", groupId: "G2", title: "G2 需求规格说明书", version: "v1", text: "用户可以提交申请。", issues: [{ id: "I1", type: "验收条件缺失", location: "第1行", status: "待教师复核", note: "" }] },
      { id: "W4", classId: "C2", groupId: "G4", title: "G4 需求规格说明书", version: "v1", text: "学生可查看文档。", issues: [{ id: "I1", type: "章节缺项", location: "TPL-06", status: "待教师复核", note: "" }] }
    ]
  };
  const clone = (value) => JSON.parse(JSON.stringify(value));
  class ClassroomDemo {
    constructor(data = initial) { this.data = clone(data); this.log = []; }
    classesFor(actor) {
      return this.data.classes.filter((classroom) => classroom.teacher === actor || this.data.groups.some((group) => group.classId === classroom.id && group.members.includes(actor))).map(clone);
    }
    isTeacher(actor, classId) {
      return this.data.classes.some((classroom) => classroom.id === classId && classroom.teacher === actor);
    }
    rows(actor, classId) {
      if (!this.isTeacher(actor, classId)) throw new Error("拒绝：教师只能查看本人负责的课程教学班。");
      return this.data.groups.filter((group) => group.classId === classId).map((group) => {
        const work = this.data.works.find((item) => item.groupId === group.id);
        if (work && work.classId !== classId) throw new Error("作品与小组的教学班归属不一致。");
        return { groupId: group.id, submitted: Boolean(work), workId: work?.id || null, title: work?.title || "未提交", version: work?.version || "—", pending: work ? work.issues.filter((issue) => issue.status === "待教师复核" || issue.status === "待核实").length : null };
      });
    }
    work(actor, workId) {
      const work = this.data.works.find((item) => item.id === workId);
      const group = work && this.data.groups.find((item) => item.id === work.groupId);
      if (!work || !group || !this.data.classes.some((item) => item.id === work.classId) || group.classId !== work.classId || (!this.isTeacher(actor, work.classId) && !group.members.includes(actor))) {
        throw new Error("拒绝：作品归属或访问权限不符，不返回原文。");
      }
      return clone(work);
    }
    ownWorks(actor, classId) {
      return this.data.works.filter((work) => work.classId === classId && this.data.groups.some((group) => group.id === work.groupId && group.classId === work.classId && group.members.includes(actor))).map(clone);
    }
    decide(actor, workId, issueId, decision, note) {
      const work = this.work(actor, workId);
      if (!this.isTeacher(actor, work.classId)) throw new Error("拒绝：学生不能作教师复核决定。");
      if (!["已确认", "已驳回", "待核实"].includes(decision) || !note.trim()) throw new Error("请填写本次复核理由并选择有效决定。");
      const issue = this.data.works.find((item) => item.id === workId).issues.find((item) => item.id === issueId);
      if (!issue) throw new Error("问题不属于当前作品。");
      const record = { actor, classId: work.classId, groupId: work.groupId, workId, version: work.version, issueId, before: issue.status, decision, note: note.trim() };
      issue.status = decision;
      issue.note = note.trim();
      this.log.push(record);
      return clone(record);
    }
  }
  if (typeof module !== "undefined") module.exports = ClassroomDemo;
  else root.ClassroomDemo = ClassroomDemo;
})(globalThis);
