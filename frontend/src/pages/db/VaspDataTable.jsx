import VaspRecordTable from './VaspRecordTable';

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
  return (
    <VaspRecordTable
      records={tasks}
      columns={columns}
      metadata={metadata}
      loading={loading}
      loadedOnce={loadedOnce}
      detailPathForItem={(item) => (
        item?._dbKey && item?._rowId
          ? `/dashboard/db/vasp/task/${encodeURIComponent(item._dbKey)}/${encodeURIComponent(String(item._rowId))}`
          : ''
      )}
      renderActions={(item) => (
        <RowActions
          item={item}
          customDbs={customDbs}
          dbScope={dbScope}
          removingRowId={removingRowId}
          onOpenParams={onOpenParams}
          onCollect={onCollect}
          onRemove={onRemove}
        />
      )}
    />
  );
}
