import { Link, useLocation } from 'react-router-dom';
import CenterLoadingOverlay from '../../components/CenterLoadingOverlay';
import { formatVaspValue, getVaspColumnPresentation } from './vaspTablePresentation';
import './VaspDataTable.css';

function RowActions({ item, customDbs, dbScope, removingRowId, onOpenParams, onCollect, onRemove }) {
  return (
    <div className="vasp-row-actions">
      <button type="button" onClick={() => onOpenParams(item)}>输入参数</button>
      <button
        type="button"
        disabled={customDbs.length === 0}
        onClick={() => onCollect(item)}
        title={customDbs.length === 0 ? '暂无自定义库（请先在入口创建）' : '收藏到自定义库'}
      >
        收藏
      </button>
      {dbScope === 'custom' ? (
        <button
          type="button"
          className="is-danger"
          onClick={() => onRemove(item)}
          disabled={removingRowId === item._rowId}
        >
          {removingRowId === item._rowId ? '移除中…' : '移除'}
        </button>
      ) : null}
    </div>
  );
}

function IdValue({ item, value }) {
  const location = useLocation();
  const rowId = item?._rowId ?? item?.row_id ?? item?.id ?? value;
  const dbKey = item?._dbKey;
  if (!rowId || !dbKey) return rowId ?? '-';

  return (
    <Link
      className="vasp-row-link"
      to={`/dashboard/db/vasp/task/${encodeURIComponent(dbKey)}/${encodeURIComponent(String(rowId))}`}
      state={{ backTo: `${location.pathname}${location.search}` }}
      title="打开任务详情（支持新标签页）"
    >
      {String(rowId)}
    </Link>
  );
}

function Value({ column, item, metadata }) {
  const value = item?.[column];
  if (column === 'id' || column === '_rowId' || column === 'row_id') {
    return <IdValue item={item} value={value} />;
  }
  const formatted = formatVaspValue(column, value, metadata);
  const presentation = getVaspColumnPresentation(column, metadata);
  return (
    <span className={presentation.kind === 'path' ? 'vasp-path-value' : undefined} title={formatted.raw || undefined}>
      {formatted.display}
    </span>
  );
}

export default function VaspDataTable({
  tasks,
  columns,
  metadata,
  loading,
  loadedOnce,
  customDbs,
  dbScope,
  removingRowId,
  onOpenParams,
  onCollect,
  onRemove,
}) {
  const primaryColumns = columns.filter((column) => getVaspColumnPresentation(column, metadata).priority <= 1);
  const secondaryColumns = columns.filter((column) => !primaryColumns.includes(column));
  const columnCount = Math.max(1, columns.length + 1);

  const actions = (item) => (
    <RowActions
      item={item}
      customDbs={customDbs}
      dbScope={dbScope}
      removingRowId={removingRowId}
      onOpenParams={onOpenParams}
      onCollect={onCollect}
      onRemove={onRemove}
    />
  );

  return (
    <div className="vasp-data-surface">
      {loading ? <CenterLoadingOverlay text="正在加载，请不要重复点击和刷新界面" /> : null}

      <div className="vasp-table-scroll">
        <table className="vasp-data-table">
          <thead>
            <tr>
              {columns.map((column) => {
                const meta = getVaspColumnPresentation(column, metadata);
                return (
                  <th key={column} title={`原始字段：${column}`}>
                    <span>{meta.label}</span>
                    {meta.unit ? <small>{meta.unit}</small> : null}
                  </th>
                );
              })}
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {loading && !loadedOnce ? (
              <tr><td colSpan={columnCount} className="vasp-table-message">正在加载…</td></tr>
            ) : tasks.length === 0 ? (
              <tr><td colSpan={columnCount} className="vasp-table-message">暂无匹配记录</td></tr>
            ) : tasks.map((item, index) => (
              <tr key={`${item._dbKey || 'db'}:${item._rowId || item.id || index}`}>
                {columns.map((column) => (
                  <td key={column}><Value column={column} item={item} metadata={metadata} /></td>
                ))}
                <td>{actions(item)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="vasp-mobile-records">
        {loading && !loadedOnce ? <div className="vasp-mobile-message">正在加载…</div> : null}
        {!loading && tasks.length === 0 ? <div className="vasp-mobile-message">暂无匹配记录</div> : null}
        {tasks.map((item, index) => (
          <article className="vasp-mobile-record" key={`${item._dbKey || 'db'}:${item._rowId || item.id || index}`}>
            <div className="vasp-mobile-record-head">
              <strong><Value column="formula" item={item} metadata={metadata} /></strong>
              <span><Value column="id" item={item} metadata={metadata} /></span>
            </div>
            <dl className="vasp-mobile-primary-fields">
              {primaryColumns.filter((column) => !['id', 'formula'].includes(column)).map((column) => {
                const meta = getVaspColumnPresentation(column, metadata);
                return (
                  <div key={column}>
                    <dt>{meta.label}{meta.unit ? ` (${meta.unit})` : ''}</dt>
                    <dd><Value column={column} item={item} metadata={metadata} /></dd>
                  </div>
                );
              })}
            </dl>
            {secondaryColumns.length ? (
              <details>
                <summary>更多字段</summary>
                <dl>
                  {secondaryColumns.map((column) => {
                    const meta = getVaspColumnPresentation(column, metadata);
                    return <div key={column}><dt>{meta.label}</dt><dd><Value column={column} item={item} metadata={metadata} /></dd></div>;
                  })}
                </dl>
              </details>
            ) : null}
            {actions(item)}
          </article>
        ))}
      </div>
    </div>
  );
}
