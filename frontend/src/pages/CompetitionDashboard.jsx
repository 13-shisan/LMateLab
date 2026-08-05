import { Activity, Atom, Database, ShieldCheck } from 'lucide-react';

import { canWriteCompetitionData, roleLabel } from '../config/competitionAccess';


function readStoredUser() {
  try {
    return JSON.parse(localStorage.getItem('user') || 'null');
  } catch {
    return null;
  }
}

export default function CompetitionDashboard() {
  const user = readStoredUser();
  const writable = canWriteCompetitionData(user);

  return (
    <div className="lm-dashboard-page">
      <section className="lm-dashboard-welcome">
        <div>
          <h2>107 杯计算工作台</h2>
          <p>固定 MoS2 计算闭环</p>
        </div>
      </section>

      <section className="lm-overview-grid" aria-label="竞赛平台概览">
        <article className="lm-overview-item">
          <div className="lm-overview-label">
            <span>平台状态</span>
            <span className="lm-overview-icon"><Activity size={16} /></span>
          </div>
          <strong className="is-healthy">正常运行</strong>
          <small>107 Slurm 计算节点</small>
        </article>
        <article className="lm-overview-item">
          <div className="lm-overview-label">
            <span>当前身份</span>
            <span className="lm-overview-icon"><ShieldCheck size={16} /></span>
          </div>
          <strong>{roleLabel(user?.role)}</strong>
          <small>{writable ? '受控操作权限' : '只读演示权限'}</small>
        </article>
        <article className="lm-overview-item">
          <div className="lm-overview-label">
            <span>计算模板</span>
            <span className="lm-overview-icon"><Atom size={16} /></span>
          </div>
          <strong>MoS2</strong>
          <small>relax / SCF / BAND / DOS</small>
        </article>
        <article className="lm-overview-item">
          <div className="lm-overview-label">
            <span>工作流记录</span>
            <span className="lm-overview-icon"><Database size={16} /></span>
          </div>
          <strong>0</strong>
          <small>当前竞赛数据库</small>
        </article>
      </section>

      <section className="lm-dashboard-panel">
        <div className="lm-dashboard-panel-header">
          <div>
            <h3>计算工作流</h3>
            <p>暂无工作流记录</p>
          </div>
        </div>
      </section>
    </div>
  );
}
