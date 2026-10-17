#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能家居 · 机械门禁（全规范版）—— 入口

覆盖：00 宪章 · 01 总览 · 02 视觉 · 03 功能与交互 · 04 主动性 · 05 技术架构
      06 设备接入与命名 · 07 数据与记忆 · 08 安全与隐私 · 09 开发验收与运维 · 11 代码规范

规则：
  - 每条检查都标注它守的规范（cid 前缀 = 规范编号）。
  - PASS = 机械验证通过；FAIL = 违反；SKIP = 尚未适用的阶段（必须写明原因，不算通过）。
  - 退出码非 0 表示有 FAIL。门禁自身判据错了要修门禁，不许绕过。
  - 拆分为 gatebase（基座）/ gatechecks / gatechecks2 / gatechecks3 / gatechecks4，见 11 §3 文件规模要求。

用法：python3 tools/gate.py [--init]
"""
import sys

import gatebase
from gatebase import R, rec
import gatechecks as G1
import gatechecks2 as G2
import gatechecks3 as G3
import gatechecks4 as G4


def main():
    init = '--init' in sys.argv
    for fn in (lambda: G1.c01(), lambda: G1.c02(), lambda: G1.c03(), lambda: G1.c04(init),
               G1.l01, G1.l02, G1.v01, G1.v02, G1.v03, G1.v04, G1.v05, G1.v06, G1.v07, G1.v08,
               G1.i01, G1.i02, G1.i03, G1.i04, G1.a01, G1.a02, G1.a03, G2.a04, G2.a05,
               G1.t01, G1.t02, G1.t03, G1.t04, G1.t05,
               G1.d01, G1.d02, G1.d03, G1.d04, G1.d05, G1.d06,
               G2.m01, G2.m02, G2.m03, G2.m04, G2.m05,
               G2.s01, G2.s03, G2.s04, G2.s05, G2.s06,
               G2.q01, G2.q02, G2.q03, G2.q04, G2.q05, G2.q06, G2.q07, G2.q08, G2.q09, G2.q10, G2.q11, G2.q12, G2.q13, G2.q14, G2.q16, G2.q17, G2.q18, G2.q19, G2.q20, G3.q21, G3.q22, G3.q23, G3.q24, G3.q25, G3.q26, G3.q27, G3.q28, G3.q29, G3.q30, G3.q31, G3.q32, G3.q33, G3.q34, G3.q35, G3.q36, G3.q37, G3.q38, G3.q39, G3.q40, G3.q41, G3.q42, G4.q43, G4.q44, G4.q45, G4.q46, G4.q47, G4.q48, G4.q49, G4.q50, G4.q51, G4.q52, G4.q53, G4.q54, G4.q55, G4.q56,
               G2.r01, G2.r02, G2.r03, G2.r04, G2.r05, G2.r06, G2.r07, G2.r08, G3.r09):
        fn()

    w = max(len(n) for _, n, _, _ in R)
    label = {'C': '00 宪章', 'L': '01 总览', 'V': '02 视觉', 'I': '03 功能与交互', 'A': '04 主动性',
             'T': '05 技术架构', 'D': '06 设备接入与命名', 'M': '07 数据与记忆',
             'S': '08 安全与隐私', 'Q': '09 开发验收与运维', 'R': '11 代码规范'}
    print('\n智能家居 · 机械门禁（全规范版）' + ('  [首次基线登记]' if init else ''))
    print('═' * (w + 36))
    cur = ''
    for cid, name, status, detail in R:
        if cid[0] != cur:
            cur = cid[0]
            print(f'\n【{label.get(cur, cur)}】')
        print(f'{"✅" if status == "PASS" else ("❌" if status == "FAIL" else "⏭️")} {cid} {name.ljust(w)}  {detail}')
    n_pass = sum(1 for x in R if x[2] == 'PASS')
    n_fail = sum(1 for x in R if x[2] == 'FAIL')
    print('\n' + '═' * (w + 36))
    print(f'通过 {n_pass} · 失败 {n_fail} · 跳过 {len(R) - n_pass - n_fail}'
          + (f'　失败：{[c for c, _, s, _ in R if s == "FAIL"]}' if n_fail else '　全绿'))
    return 1 if n_fail else 0


if __name__ == '__main__':
    sys.exit(main())
