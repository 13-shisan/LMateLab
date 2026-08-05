import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

function fixed(value, decimals, suffix = '') {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(decimals)}${suffix}` : '-';
}

export default function VaspCrystalDetails({ detail }) {
  const [expanded, setExpanded] = useState(false);
  const crystal = detail?.crystal || {};
  const lattice = crystal.lattice || {};
  const positions = Array.isArray(crystal.atomic_positions_frac) ? crystal.atomic_positions_frac : [];
  const hasMore = positions.length > 10;
  const visiblePositions = hasMore && !expanded ? positions.slice(0, 10) : positions;

  return (
    <>
      <div className="vasp-crystal-grid">
        <div className="vasp-detail-subsection">
          <h4>晶格参数</h4>
          <dl className="vasp-crystal-fields">
            <div className="vasp-detail-field"><dt>a</dt><dd>{fixed(lattice.a, 4, ' Å')}</dd></div>
            <div className="vasp-detail-field"><dt>b</dt><dd>{fixed(lattice.b, 4, ' Å')}</dd></div>
            <div className="vasp-detail-field"><dt>c</dt><dd>{fixed(lattice.c, 4, ' Å')}</dd></div>
            <div className="vasp-detail-field"><dt>α</dt><dd>{fixed(lattice.alpha, 2, '°')}</dd></div>
            <div className="vasp-detail-field"><dt>β</dt><dd>{fixed(lattice.beta, 2, '°')}</dd></div>
            <div className="vasp-detail-field"><dt>γ</dt><dd>{fixed(lattice.gamma, 2, '°')}</dd></div>
            <div className="vasp-detail-field"><dt>晶胞体积</dt><dd>{fixed(lattice.volume, 3, ' Å³')}</dd></div>
          </dl>
        </div>
        <div className="vasp-detail-subsection">
          <h4>结构属性</h4>
          <dl className="vasp-crystal-fields">
            <div className="vasp-detail-field"><dt>原子数</dt><dd>{detail?.row?.natoms ?? '-'}</dd></div>
            <div className="vasp-detail-field"><dt>密度</dt><dd>{fixed(crystal.density_g_cm3, 3, ' g·cm⁻³')}</dd></div>
            <div className="vasp-detail-field"><dt>周期维度</dt><dd>{crystal.dimensionality == null ? '-' : `${crystal.dimensionality}D`}</dd></div>
            <div className="vasp-detail-field"><dt>空间群</dt><dd>{detail?.properties?.spacegroup ?? '-'}</dd></div>
          </dl>
        </div>
      </div>

      <div className="vasp-detail-subsection vasp-coordinate-panel">
        <div className="vasp-coordinate-header">
          <div>
            <h4>原子分数坐标</h4>
            {hasMore && !expanded ? <span>显示前 10 行，共 {positions.length} 行</span> : null}
          </div>
          {hasMore ? (
            <button className="vasp-detail-button" type="button" onClick={() => setExpanded((value) => !value)}>
              {expanded ? <ChevronUp size={15} aria-hidden="true" /> : <ChevronDown size={15} aria-hidden="true" />}
              {expanded ? '收起' : '展开全部'}
            </button>
          ) : null}
        </div>
        {positions.length > 0 ? (
          <div className="vasp-detail-table-scroll">
            <table className="vasp-detail-table">
              <thead><tr><th>序号</th><th>元素</th><th>x</th><th>y</th><th>z</th></tr></thead>
              <tbody>
                {visiblePositions.map((position, index) => (
                  <tr key={`${position?.element || 'atom'}-${index}`}>
                    <td>{index + 1}</td>
                    <td>{position?.element || '-'}</td>
                    <td>{fixed(position?.x, 6)}</td>
                    <td>{fixed(position?.y, 6)}</td>
                    <td>{fixed(position?.z, 6)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <div className="vasp-detail-message">暂无原子分数坐标</div>}
      </div>
    </>
  );
}
