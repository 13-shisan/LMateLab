import { ArrowDown, ArrowRight, Database, LogIn, ShieldCheck, Workflow } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import campusAutumn from '../../assets/107cup/campus-lake.webp';
import campusSpring from '../../assets/107cup/campus-spring.webp';
import campusSummer from '../../assets/107cup/campus-summer.webp';
import campusWinter from '../../assets/107cup/campus-winter.webp';
import BrandMark from '../../components/BrandMark';
import './CompetitionHome.css';

const FLOW_STEPS = Object.freeze([
  { number: '01', key: 'relax', title: '结构优化', detail: '固定晶体结构与计算模板' },
  { number: '02', key: 'SCF', title: '自洽计算', detail: '形成可信电子基态' },
  { number: '03', key: 'BAND', title: '能带计算', detail: '解析能带路径与带隙' },
  { number: '04', key: 'DOS', title: '态密度计算', detail: '输出总态密度与投影数据' },
]);

export default function CompetitionHome() {
  const navigate = useNavigate();

  return (
    <div className="competition-home">
      <header className="competition-home-nav">
        <button
          className="competition-home-brand"
          type="button"
          onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
          aria-label="返回 LMateLab 首页顶部"
        >
          <BrandMark />
        </button>
        <nav className="competition-home-links" aria-label="首页导航">
          <a href="#platform">平台</a>
          <a href="#workflow">工作流</a>
          <a href="#evidence">证据</a>
        </nav>
        <button
          className="competition-home-login"
          type="button"
          onClick={() => navigate('/login')}
          aria-label="进入平台"
        >
          <LogIn size={17} aria-hidden="true" />
          <span>进入平台</span>
        </button>
      </header>

      <main>
        <section
          className="competition-home-hero"
          style={{ '--competition-home-hero-image': `url(${campusSpring})` }}
          aria-labelledby="competition-home-title"
        >
          <div className="competition-home-hero-content">
            <p className="competition-home-kicker">中国科学技术大学 · 低维材料科学实验室</p>
            <h1 id="competition-home-title">LMateLab</h1>
            <p className="competition-home-lead">面向二维材料的可追溯 VASP 计算平台</p>
            <p className="competition-home-summary">
              围绕固定 MoS2 主线，把计算输入、Slurm 作业、科学验收与结构、BAND、DOS
              结果组织成一条可以复核的证据链。
            </p>
            <div className="competition-home-actions">
              <button type="button" onClick={() => navigate('/login')}>
                <LogIn size={18} aria-hidden="true" />
                进入平台
              </button>
              <a href="#workflow">
                查看计算闭环
                <ArrowDown size={17} aria-hidden="true" />
              </a>
            </div>
            <p className="competition-home-release">107 杯竞赛版本 · 计算、数据与证据均位于 107 服务器</p>
          </div>
        </section>

        <section
          id="platform"
          className="competition-home-campus"
          style={{ '--competition-home-campus-image': `url(${campusSummer})` }}
          aria-labelledby="competition-home-platform-title"
        >
          <div className="competition-home-campus-inner">
            <div className="competition-home-campus-copy">
              <p className="competition-home-section-label">平台主线</p>
              <h2 id="competition-home-platform-title">从结构到证据</h2>
              <p>
                以固定输入和固定命令封装控制计算范围，让每一步结果都能追溯到发布提交、
                Slurm Job ID、原始文件与验收结论。
              </p>
            </div>
            <div className="competition-home-pillars" aria-label="平台能力">
              <div>
                <Workflow size={22} aria-hidden="true" />
                <strong>固定流程</strong>
                <span>MoS2 四步 VASP 闭环</span>
              </div>
              <div>
                <ShieldCheck size={22} aria-hidden="true" />
                <strong>调度可信</strong>
                <span>Slurm 归属核验与失败关闭</span>
              </div>
              <div>
                <Database size={22} aria-hidden="true" />
                <strong>结果可查</strong>
                <span>结构、能带、态密度与证据包</span>
              </div>
            </div>
          </div>
        </section>

        <section
          id="workflow"
          className="competition-home-flow"
          style={{ '--competition-home-flow-image': `url(${campusAutumn})` }}
          aria-labelledby="competition-home-flow-title"
        >
          <div className="competition-home-section-heading">
            <p className="competition-home-section-label">计算工作流</p>
            <h2 id="competition-home-flow-title">四步 VASP 闭环</h2>
            <p>前一步科学验收通过后，下一步才会进入 Slurm 调度。</p>
          </div>
          <ol className="competition-home-flow-list">
            {FLOW_STEPS.map((step) => (
              <li key={step.key}>
                <span className="competition-home-flow-number">{step.number}</span>
                <strong>{step.key}</strong>
                <h3>{step.title}</h3>
                <p>{step.detail}</p>
              </li>
            ))}
          </ol>
        </section>

        <section
          id="evidence"
          className="competition-home-evidence"
          style={{ '--competition-home-evidence-image': `url(${campusWinter})` }}
          aria-labelledby="competition-home-evidence-title"
        >
          <div className="competition-home-evidence-inner">
            <div>
              <p className="competition-home-section-label">验收证据</p>
              <h2 id="competition-home-evidence-title">结果不是一张孤立的图</h2>
            </div>
            <p>
              工作流状态、attempt 目录、资源记录、输出 SHA-256、结构视图、BAND 与 DOS
              共同构成最终结果。失败算例同样保留原因和阻断链，不把未收敛结果显示为成功。
            </p>
          </div>
        </section>

        <section className="competition-home-entry" aria-label="平台入口">
          <div>
            <p className="competition-home-section-label">LMateLab 107 Cup</p>
            <h2>进入计算工作台</h2>
          </div>
          <button type="button" onClick={() => navigate('/login')}>
            <span>登录平台</span>
            <ArrowRight size={18} aria-hidden="true" />
          </button>
        </section>
      </main>

      <footer className="competition-home-footer">
        <BrandMark />
        <p>中国科学技术大学 · 低维材料科学实验室 · 107 杯竞赛平台</p>
      </footer>
    </div>
  );
}
