// src/pages/Home.jsx
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, Compass, LogIn } from 'lucide-react';

import homeBg from '../assets/bg/home-bg.png';
import BrandMark from '../components/BrandMark';

export default function Home() {
  const navigate = useNavigate();

  useEffect(() => {
    const id = window.location.hash?.replace('#', '');
    if (!id) return;
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  const scrollTo = (id) => {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="home-page">
      <header className="home-nav">
        <div
          className="home-nav-left"
          role="button"
          tabIndex={0}
          onClick={() => scrollTo('top')}
          onKeyDown={(e) => e.key === 'Enter' && scrollTo('top')}
        >
          <BrandMark />
        </div>

        <nav className="home-nav-right">
          <button className="home-link" onClick={() => scrollTo('features')}>平台介绍</button>
          <button className="home-link" onClick={() => scrollTo('modules')}>核心能力</button>
          <button className="home-link" onClick={() => scrollTo('cases')}>应用案例</button>
          <button className="home-link" onClick={() => scrollTo('docs')}>帮助文档</button>

          <button className="home-header-login" onClick={() => navigate('/login')}>
            <LogIn size={16} />
            <span>登录</span>
          </button>
        </nav>
      </header>

      {/* ✅ 只有首屏使用背景图 */}
      <section
        id="top"
        className="home-hero home-with-bg"
        style={{ '--page-bg': `url(${homeBg})` }}
      >
        <div className="home-hero-inner home-hero-inner-shift">
          <h1 className="home-hero-title">面向材料设计的计算化学平台</h1>
          <p className="home-hero-subtitle">
            集成高通量计算、文献管理与实验记录，帮助科研人员高效完成从计算到数据管理的全流程。
          </p>

          <div className="home-hero-actions">
            <button className="home-cta home-cta-explore" onClick={() => scrollTo('features')}>
              <Compass size={18} />
              <span>了解平台</span>
              <ArrowRight size={15} />
            </button>
            <button className="home-cta home-cta-login" onClick={() => navigate('/login')}>
              <LogIn size={18} />
              <span>进入登录</span>
            </button>
          </div>

          <div className="home-hero-hint">向下滚动查看介绍</div>
        </div>

        <div className="home-hero-bg" aria-hidden="true" />
      </section>

      <section id="features" className="home-section">
        <div className="home-section-inner">
          <h2 className="home-section-title">平台介绍</h2>
          <p className="home-section-desc">
            将计算任务、数据沉淀、知识管理与协作整合到统一入口，减少重复劳动，让产出更可复用。
          </p>

          <div className="home-cards">
            <div className="home-card">
              <h3>高通量计算</h3>
              <p>任务批量提交、状态追踪、结果归档与可检索。</p>
            </div>
            <div className="home-card">
              <h3>实验/计算记录</h3>
              <p>模板化记录、可追溯修改、方便团队协作。</p>
            </div>
            <div className="home-card">
              <h3>数据与文献管理</h3>
              <p>统一索引、分类标签、快速搜索，形成实验室知识库。</p>
            </div>
          </div>
        </div>
      </section>

      <section id="modules" className="home-section home-section-alt">
        <div className="home-section-inner">
          <h2 className="home-section-title">核心能力</h2>

          <div className="home-grid">
            <div className="home-grid-item">
              <div className="home-kpi">任务</div>
              <div className="home-grid-title">多类型计算流程</div>
              <div className="home-grid-desc">
                支持不同计算软件/流程的统一入口与规范化管理（按实际模块补充）。
              </div>
            </div>

            <div className="home-grid-item">
              <div className="home-kpi">数据</div>
              <div className="home-grid-title">结果沉淀与可追踪</div>
              <div className="home-grid-desc">
                参数、结构、结果统一归档；失败任务定位更快；可复用更强。
              </div>
            </div>

            <div className="home-grid-item">
              <div className="home-kpi">协作</div>
              <div className="home-grid-title">团队协作与权限</div>
              <div className="home-grid-desc">
                统一账号体系、权限控制、共享与审计（逐步增强）。
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="cases" className="home-section">
        <div className="home-section-inner">
          <h2 className="home-section-title">应用案例</h2>
          <p className="home-section-desc">这里先放占位内容，后续可替换成你们真实成果与配图。</p>

          <div className="home-cases">
            <div className="home-case">
              <div className="home-case-title">案例 1：二维材料缺陷与掺杂筛选</div>
              <div className="home-case-desc">
                从结构生成 → 批量计算 → 结果对比 → 形成可复用数据集。
              </div>
            </div>

            <div className="home-case">
              <div className="home-case-title">案例 2：催化表面吸附能高通量</div>
              <div className="home-case-desc">
                多任务并行，结果统一归档与检索，显著缩短“找数据”的时间。
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="docs" className="home-section home-section-alt">
        <div className="home-section-inner">
          <h2 className="home-section-title">帮助文档</h2>
          <p className="home-section-desc">
            这里可接入实验室内部 Wiki / 文档站。当前先保留入口位。
          </p>

          <div className="home-doc-actions">
            <button className="btn btn-primary" onClick={() => navigate('/login')}>
              去登录
            </button>
          </div>
        </div>
      </section>

      <footer className="home-footer">
        <div className="home-footer-text">
          copyright © 2024‑2025 低维材料科学实验室平台
          <br />
          中国科学技术大学物质楼‑Wugroup
        </div>
      </footer>
    </div>
  );
}
