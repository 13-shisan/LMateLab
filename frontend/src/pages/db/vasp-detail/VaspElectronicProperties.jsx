import { useEffect, useMemo, useState } from 'react';
import { Download } from 'lucide-react';

export default function VaspElectronicProperties({
  rowId,
  dbKey,
  capabilities,
  fetchJson,
  downloadFile,
}) {
  const bandAvailable = Boolean(capabilities?.band_plot);
  const dosAvailable = Boolean(capabilities?.dos_plot);
  const [activeTab, setActiveTab] = useState(() => (bandAvailable ? 'band' : 'dos'));
  const [plotCache, setPlotCache] = useState({ band: '', dos: '' });
  const [loadingTab, setLoadingTab] = useState('');
  const [errors, setErrors] = useState({ band: '', dos: '', download: '' });
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    setPlotCache({ band: '', dos: '' });
    setErrors({ band: '', dos: '', download: '' });
    setActiveTab(bandAvailable ? 'band' : 'dos');
  }, [bandAvailable, dbKey, dosAvailable, rowId]);

  useEffect(() => {
    const activeAvailable = activeTab === 'band' ? bandAvailable : dosAvailable;
    if (!activeAvailable || plotCache[activeTab]) return undefined;

    const controller = new AbortController();
    const encodedId = encodeURIComponent(rowId);
    const encodedDb = encodeURIComponent(dbKey);
    const path = activeTab === 'band'
      ? `/api/db/vasp/task/${encodedId}/band-plot?db=${encodedDb}`
      : `/api/db/vasp/task/${encodedId}/dos-plot?db=${encodedDb}&emin=-3&emax=3`;

    setLoadingTab(activeTab);
    setErrors((current) => ({ ...current, [activeTab]: '' }));
    fetchJson(path, { signal: controller.signal })
      .then((data) => {
        const imageSource = data?.image_url
          || (data?.image_base64 ? `data:image/png;base64,${data.image_base64}` : '');
        setPlotCache((current) => ({ ...current, [activeTab]: imageSource }));
      })
      .catch((error) => {
        if (error?.name !== 'AbortError') {
          setErrors((current) => ({ ...current, [activeTab]: String(error?.message || error) }));
        }
      })
      .finally(() => setLoadingTab((current) => (current === activeTab ? '' : current)));

    return () => controller.abort();
  }, [activeTab, bandAvailable, dbKey, dosAvailable, fetchJson, plotCache, rowId]);

  const activeAvailable = activeTab === 'band' ? bandAvailable : dosAvailable;
  const activeImage = plotCache[activeTab];
  const activeError = errors[activeTab];
  const dataAvailable = activeTab === 'band'
    ? Boolean(capabilities?.band_data)
    : Boolean(capabilities?.dos_data);
  const plotAlt = activeTab === 'band' ? '能带图' : '态密度图';
  const downloadSpec = useMemo(() => {
    const encodedId = encodeURIComponent(rowId);
    const encodedDb = encodeURIComponent(dbKey);
    return activeTab === 'band'
      ? { path: `/api/db/vasp/task/${encodedId}/band-dat?db=${encodedDb}&align=fermi`, filename: `${rowId}_band.dat` }
      : { path: `/api/db/vasp/task/${encodedId}/dos-dat?db=${encodedDb}&align=fermi&decimate=1`, filename: `${rowId}_dos_data.zip` };
  }, [activeTab, dbKey, rowId]);

  async function handleDownload() {
    setDownloading(true);
    setErrors((current) => ({ ...current, download: '' }));
    try {
      await downloadFile(downloadSpec.path, downloadSpec.filename);
    } catch (error) {
      setErrors((current) => ({ ...current, download: String(error?.message || error) }));
    } finally {
      setDownloading(false);
    }
  }

  if (!bandAvailable && !dosAvailable) {
    return <div className="vasp-detail-message">该记录没有可用的能带或 DOS 源文件</div>;
  }

  return (
    <>
      <div className="vasp-electronic-toolbar">
        <div className="vasp-electronic-tabs" role="tablist" aria-label="电子性质">
          <button className={activeTab === 'band' ? 'is-active' : ''} type="button" disabled={!bandAvailable} onClick={() => setActiveTab('band')}>能带</button>
          <button className={activeTab === 'dos' ? 'is-active' : ''} type="button" disabled={!dosAvailable} onClick={() => setActiveTab('dos')}>态密度 (DOS)</button>
        </div>
        <button className="vasp-detail-button" type="button" disabled={!dataAvailable || downloading} onClick={handleDownload}>
          <Download size={15} aria-hidden="true" />
          {downloading ? '正在导出…' : '导出当前数据'}
        </button>
      </div>
      <div className="vasp-plot-panel" role="tabpanel">
        {!activeAvailable ? <div className="vasp-detail-message">当前数据不可用</div> : null}
        {loadingTab === activeTab ? <div className="vasp-detail-message">正在生成{plotAlt}…</div> : null}
        {activeError ? <div className="vasp-detail-message vasp-detail-error">加载失败：{activeError}</div> : null}
        {activeImage ? <img src={activeImage} alt={plotAlt} /> : null}
      </div>
      {errors.download ? <div className="vasp-detail-error" role="alert">导出失败：{errors.download}</div> : null}
    </>
  );
}
