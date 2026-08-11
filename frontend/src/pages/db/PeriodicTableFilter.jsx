import { matchesElementSelection, toggleElementSelection } from '../../utils/elementSelection';
import { PERIODIC_TABLE_ELEMENTS } from './periodicTableElements';
import './PeriodicTableFilter.css';

export { matchesElementSelection, toggleElementSelection };

export default function PeriodicTableFilter({
  availableElements,
  selectedElements,
  mode,
  onSelectionChange,
  onModeChange,
}) {
  const available = new Set(availableElements);
  return (
    <section className="vasp-periodic-filter" aria-label="元素周期表筛选">
      <div className="vasp-periodic-toolbar">
        <div className="vasp-segmented-control" aria-label="元素匹配模式">
          <button type="button" className={mode === 'at_least' ? 'is-active' : ''} onClick={() => onModeChange('at_least')}>至少含有所选元素</button>
          <button type="button" className={mode === 'only' ? 'is-active' : ''} onClick={() => onModeChange('only')}>只含所选元素</button>
        </div>
        <button type="button" onClick={() => onSelectionChange([])} disabled={selectedElements.length === 0}>清空选择</button>
      </div>
      <div className="vasp-selected-elements" aria-live="polite">
        {selectedElements.length === 0 ? <span>未选择元素</span> : selectedElements.map((symbol) => (
          <button key={symbol} type="button" onClick={() => onSelectionChange(toggleElementSelection(selectedElements, symbol))} title={`移除 ${symbol}`}>{symbol}</button>
        ))}
      </div>
      <div className="vasp-periodic-scroll">
        <div className="vasp-periodic-grid">
          {PERIODIC_TABLE_ELEMENTS.map((element) => {
            const present = available.has(element.symbol);
            const selected = selectedElements.includes(element.symbol);
            return (
              <button
                key={element.Z}
                type="button"
                className={`vasp-element-cell${present ? ' is-present' : ''}${selected ? ' is-selected' : ''}`}
                style={{ gridColumn: element.col, gridRow: element.row }}
                aria-pressed={selected}
                onClick={() => onSelectionChange(toggleElementSelection(selectedElements, element.symbol))}
                title={`${element.name} (${element.symbol}, Z=${element.Z})`}
              >
                <small>{element.Z}</small><strong>{element.symbol}</strong>
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}
