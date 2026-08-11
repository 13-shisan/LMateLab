import { Link, useLocation } from 'react-router-dom';
import CenterLoadingOverlay from '../../components/CenterLoadingOverlay';
import { formatVaspValue, getVaspColumnPresentation } from './vaspTablePresentation';
import './VaspDataTable.css';

function IdValue({ item, value, detailPathForItem }) {
  const location = useLocation();
  const rowId = item?._rowId ?? item?.row_id ?? item?.id ?? value;
  const detailPath = detailPathForItem?.(item);
  if (!detailPath) return rowId ?? '-';

  return (
    <Link
      className="vasp-row-link"
      to={detailPath}
      state={{ backTo: `${location.pathname}${location.search}` }}
      title="打开任务详情（支持新标签页）"
    >
      {String(rowId)}
    </Link>
  );
}

function Value({ column, item, metadata, detailPathForItem, renderCell }) {
  const rendered = renderCell?.(column, item);
  if (rendered !== undefined) return rendered;

  const value = item?.[column];
  if (column === 'id' || column === '_rowId' || column === 'row_id') {
    return <IdValue item={item} value={value} detailPathForItem={detailPathForItem} />;
  }
  const formatted = formatVaspValue(column, value, metadata);
  const presentation = getVaspColumnPresentation(column, metadata);
  return (
    <span className={presentation.kind === 'path' ? 'vasp-path-value' : undefined} title={formatted.raw || undefined}>
      {formatted.display}
    </span>
  );
}

function accessibleLabelForItem(item) {
  const formula = item?.formula;
  const rowId = item?._rowId ?? item?.row_id ?? item?.id;
  if (formula && rowId !== null && rowId !== undefined && rowId !== '') {
    return `选择 ${formula}，记录 ID ${rowId}`;
  }
  if (formula) return `选择 ${formula}`;
  if (rowId !== null && rowId !== undefined && rowId !== '') return `选择记录 ID ${rowId}`;
  return '选择 VASP 记录';
}

export default function VaspRecordTable({
  records,
  columns,
  metadata,
  loading = false,
  loadedOnce = true,
  detailPathForItem,
  onSelect = null,
  renderCell = null,
  mobileMode = 'cards',
  renderActions = null,
}) {
  const primaryColumns = columns.filter((column) => getVaspColumnPresentation(column, metadata).priority <= 1);
  const secondaryColumns = columns.filter((column) => !primaryColumns.includes(column));
  const hasActions = typeof renderActions === 'function';
  const columnCount = columns.length + (hasActions ? 1 : 0);

  const selectablePropsFor = (item) => {
    if (typeof onSelect !== 'function') return {};
    return {
      'aria-label': accessibleLabelForItem(item),
      onClick: () => onSelect(item),
      onKeyDown: (event) => {
        if (event.key === 'Enter' && event.currentTarget === event.target) onSelect(item);
      },
      role: 'button',
      tabIndex: 0,
    };
  };

  const valueFor = (column, item) => (
    <Value
      column={column}
      item={item}
      metadata={metadata}
      detailPathForItem={detailPathForItem}
      renderCell={renderCell}
    />
  );

  return (
    <div className={`vasp-data-surface${mobileMode === 'scroll' ? ' is-mobile-scroll' : ''}`}>
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
              {hasActions ? <th>操作</th> : null}
            </tr>
          </thead>
          <tbody>
            {loading && !loadedOnce ? (
              <tr><td colSpan={columnCount} className="vasp-table-message">正在加载…</td></tr>
            ) : records.length === 0 ? (
              <tr><td colSpan={columnCount} className="vasp-table-message">暂无匹配记录</td></tr>
            ) : records.map((item, index) => (
              <tr
                key={`${item._dbKey || 'db'}:${item._rowId || item.id || index}`}
                {...selectablePropsFor(item)}
              >
                {columns.map((column) => (
                  <td key={column}>{valueFor(column, item)}</td>
                ))}
                {hasActions ? <td>{renderActions(item)}</td> : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="vasp-mobile-records">
        {loading && !loadedOnce ? <div className="vasp-mobile-message">正在加载…</div> : null}
        {!loading && records.length === 0 ? <div className="vasp-mobile-message">暂无匹配记录</div> : null}
        {records.map((item, index) => (
          <article
            className="vasp-mobile-record"
            key={`${item._dbKey || 'db'}:${item._rowId || item.id || index}`}
            {...selectablePropsFor(item)}
          >
            <div className="vasp-mobile-record-head">
              <strong>{valueFor('formula', item)}</strong>
              <span>{valueFor('id', item)}</span>
            </div>
            <dl className="vasp-mobile-primary-fields">
              {primaryColumns.filter((column) => !['id', 'formula'].includes(column)).map((column) => {
                const meta = getVaspColumnPresentation(column, metadata);
                return (
                  <div key={column}>
                    <dt>{meta.label}{meta.unit ? ` (${meta.unit})` : ''}</dt>
                    <dd>{valueFor(column, item)}</dd>
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
                    return <div key={column}><dt>{meta.label}</dt><dd>{valueFor(column, item)}</dd></div>;
                  })}
                </dl>
              </details>
            ) : null}
            {hasActions ? renderActions(item) : null}
          </article>
        ))}
      </div>
    </div>
  );
}
