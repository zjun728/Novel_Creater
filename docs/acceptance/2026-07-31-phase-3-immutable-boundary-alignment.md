# Phase 3 Immutable Boundary Alignment Acceptance

## 元数据

- Branch: `codex/phase3d-boundary-acceptance`。
- Delivery baseline: `main@e8aebd9eb851ccc64f160022984342344905cd15`。
- Functional implementation HEAD: `382dcefa57f575209cc703d3af0e60fd1b11137d`。
- Schema: `writer-core-v1.6.0`；Candidate 依据身份是精确源码 Schema 的一部分。

## 不可变边界结果

- Seed second-selection refused：首次确认后，第二次选择被服务端拒绝，原确认身份保持不变。
- Contract post-confirmation replacement refused：首次确认后不能建立替代 Contract revision。
- Bible post-confirmation replacement refused：首次确认后不能建立替代 Bible revision。
- Outline r1 -> r2：正文未定稿时，作者可把活动小纲从 r1 调整为 r2。
- Session entry provenance remains r1：既有 Session 继续保留进入写作时的 r1 pins，不被静默重绑。
- Candidate A stale：绑定 r1 的旧 Candidate 保留但标记为 stale。
- Candidate B current：基于 r2 新保存的 Candidate 标记为 current。
- Planning 只调整尚未实现的未来节点；本阶段不提供历史重开、Canon 回滚或项目分支。

## Fresh 门禁与审查

- `npm test`：Python `2871 passed, 6 skipped, 0 failed`；root Node `345/345 passed, 0 failed`；frontend `547/547 passed, 0 failed`。
- focused backend：`376 passed, 0 failed`。
- `npm run test:integration`：`341 passed, 0 failed`；`created=339, cleaned=339, remaining=0`。
- `npm run build`：Vite 8.0.13，2958 modules。
- `npm run test:browser:phase3`：browser `6/6`。
- `git diff --check`：`0`。
- Specification review: Critical/Important/Minor = 0/0/0。
- Quality review: Critical/Important/Minor = 0/0/0。
- all exit `0`。

## 资源与安全账本

- owned process `0`、port `0`、temp root `0`、Vite `deps_temp` `0`、test DB `0`。
- Real Provider calls `0`；Product DB reads/writes `0/0`；live website `0`；UI bypass `0`；secret finding `0`。
- 自动门禁仅使用 loopback、严格 fake 外部边界与一次性 MySQL 测试库。

## 明确延后

- Phase 5 finalization atomic lock and Canon realization：延后。
- Phase 5 才在一个事务中冻结最终小纲与正文、追加 Canon、重建 Projection 并推进 Planning realization。
- Setting、记忆、人物状态、伏笔与故事进度继续作为 Canon/Projection 派生视图，Phase 3 仍未交付这些能力。
