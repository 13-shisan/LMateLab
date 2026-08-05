import { useMemo, useState } from 'react';
import { ChevronDown, Download } from 'lucide-react';
import { colorForElement } from '../../../utils/elementColors';
import { formatTaskValue, getTaskFieldPresentation } from './vaspTaskDetailPresentation';

const SUMMARY_FIELDS = ['id', 'formula', 'energy', 'fmax', 'natoms', 'pbc'];
const PROPERTY_FIELDS = ['spacegroup', 'bandgap_eV', 'vbm_eV', 'cbm_eV'];

function FieldList({ values, fields }) {
  return (
    <dl className="vasp-summary-fields">
      {fields.map((key) => {
        const presentation = getTaskFieldPresentation(key);
        const formatted = formatTaskValue(key, values?.[key]);
        return (
          <div className="vasp-detail-field" key={key}>
            <dt>{presentation.label}{presentation.unit ? ` (${presentation.unit})` : ''}</dt>
            <dd title={formatted.raw || undefined}>{formatted.display}</dd>
          </div>
        );
      })}
    </dl>
  );
}

export default function VaspTaskSummary({ detail, dbKey, rowId, viewer, downloadFile }) {
  const [exportOpen, setExportOpen] = useState(false);
  const [actionError, setActionError] = useState('');
  const [downloading, setDownloading] = useState('');
  const capabilities = detail?.capabilities || {};
  const elements = useMemo(
    () => [...new Set((detail?.structure?.symbols || []).filter(Boolean))].sort(),
    [detail?.structure?.symbols],
  );

  async function download(kind, path, filename) {
    setActionError('');
    setDownloading(kind);
    try {
      await downloadFile(path, filename);
      setExportOpen(false);
    } catch (error) {
      setActionError(String(error?.message || error));
    } finally {
      setDownloading('');
    }
  }

  const encodedId = encodeURIComponent(rowId);
  const encodedDb = encodeURIComponent(dbKey);
  const exportItems = [
    {
      key: 'cif', label: '晶体结构 (CIF)', enabled: capabilities.structure_export,
      path: `/api/db/vasp/task/${encodedId}/export?db=${encodedDb}&format=cif`, filename: `${rowId}.cif`,
    },
    {
      key: 'poscar', label: '晶体结构 (POSCAR)', enabled: capabilities.structure_export,
      path: `/api/db/vasp/task/${encodedId}/export?db=${encodedDb}&format=poscar`, filename: `${rowId}.vasp`,
    },
    {
      key: 'band', label: '能带数据 (DAT)', enabled: capabilities.band_data,
      path: `/api/db/vasp/task/${encodedId}/band-dat?db=${encodedDb}&align=fermi`, filename: `${rowId}_band.dat`,
    },
    {
      key: 'dos', label: 'DOS 数据 (ZIP)', enabled: capabilities.dos_data,
      path: `/api/db/vasp/task/${encodedId}/dos-dat?db=${encodedDb}&align=fermi&decimate=1`, filename: `${rowId}_dos_data.zip`,
    },
  ];

  return (
    <div className="vasp-task-summary">
      {viewer}
      <div className="vasp-summary-panel">
        <div className="vasp-summary-database" title={dbKey}>数据库：{detail?.db?.dbname || dbKey}</div>
        <FieldList values={detail?.row} fields={SUMMARY_FIELDS} />
        <div className="vasp-summary-divider" />
        <FieldList values={detail?.properties} fields={PROPERTY_FIELDS} />

        <div className="vasp-element-legend" aria-label="元素图例">
          {elements.length > 0 ? elements.map((element) => (
            <span className="vasp-element-item" key={element}>
              <span className="vasp-element-swatch" style={{ backgroundColor: colorForElement(element) }} />
              {element}
            </span>
          )) : <span className="vasp-detail-muted">暂无元素信息</span>}
        </div>

        <div className="vasp-detail-actions">
          <div className="vasp-export-menu">
            <button
              className="vasp-detail-button"
              type="button"
              onClick={() => setExportOpen((open) => !open)}
              aria-expanded={exportOpen}
            >
              <Download size={15} aria-hidden="true" />
              导出
              <ChevronDown size={14} aria-hidden="true" />
            </button>
            {exportOpen ? (
              <div className="vasp-export-menu-panel">
                {exportItems.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    disabled={!item.enabled || Boolean(downloading)}
                    onClick={() => download(item.key, item.path, item.filename)}
                    title={!item.enabled ? '该记录没有对应的源文件' : undefined}
                  >
                    {downloading === item.key ? '正在导出…' : item.label}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </div>
        {actionError ? <div className="vasp-detail-error" role="alert">导出失败：{actionError}</div> : null}
      </div>
    </div>
  );
}
