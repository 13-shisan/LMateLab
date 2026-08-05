// src/pages/ComingSoon.jsx
import { useNavigate } from 'react-router-dom';

export default function ComingSoon() {
  const navigate = useNavigate();

  const goDashboard = () => {
    navigate('/dashboard');
  };

  return (
    <div
      style={{
        padding: '40px 24px',
        textAlign: 'center',
        fontFamily: "'Comic Sans MS', '楷体', sans-serif",
      }}
    >
      {/* 施工队招牌 */}
      <div
        style={{
          fontSize: '13px',
          background: '#ffd166',
          color: '#d00000',
          padding: '4px 12px',
          borderRadius: '20px',
          display: 'inline-block',
          marginBottom: '20px',
          fontWeight: 'bold',
          transform: 'rotate(-3deg)',
        }}
      >
        🚧 宇宙无敌施工队荣誉出品 🚧
      </div>

      <h2
        style={{
          marginTop: 0,
          fontSize: '2.5em',
          background: 'linear-gradient(45deg, #ff6b6b, #4ecdc4)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
          marginBottom: '10px',
        }}
      >
        功能正在紧急施工中！
      </h2>

      {/* 动态表情 */}
      <div style={{ fontSize: '60px', margin: '20px 0' }}>
        <span style={{ display: 'inline-block', animation: 'bounce 1s infinite' }}>👷</span>
        <span
          style={{
            display: 'inline-block',
            animation: 'bounce 1s infinite 0.2s',
            margin: '0 15px',
          }}
        >
          🔨
        </span>
        <span style={{ display: 'inline-block', animation: 'bounce 1s infinite 0.4s' }}>🚧</span>
      </div>

      <p
        style={{
          color: '#6b7280',
          fontSize: '1.2em',
          lineHeight: 1.6,
          maxWidth: '600px',
          margin: '0 auto 30px',
        }}
      >
        程序员正在疯狂敲代码，键盘已经冒烟啦！
        <br />
        这个功能就像初恋——
        <span
          style={{
            color: '#ef4444',
            fontWeight: 'bold',
            textDecoration: 'underline wavy',
          }}
        >
          美好但需要一点时间
        </span>
        ～
      </p>

      {/* 进度条彩蛋 */}
      <div
        style={{
          background: '#e5e7eb',
          borderRadius: '10px',
          height: '20px',
          width: '80%',
          maxWidth: '400px',
          margin: '30px auto',
          overflow: 'hidden',
          position: 'relative',
        }}
      >
        <div
          style={{
            position: 'absolute',
            width: '66%',
            height: '100%',
            background: 'linear-gradient(90deg, #4ecdc4, #45b7d1)',
            animation: 'shimmer 2s infinite',
            borderRadius: '10px',
          }}
        />
        <div
          style={{
            position: 'absolute',
            right: '10px',
            top: '50%',
            transform: 'translateY(-50%)',
            color: 'white',
            fontSize: '12px',
            fontWeight: 'bold',
            textShadow: '1px 1px 2px rgba(0,0,0,0.3)',
          }}
        >
          加载幽默感中... 66%
        </div>
      </div>

      {/* 警告标语 */}
      <div
        style={{
          marginTop: '40px',
          padding: '15px',
          background: '#fef3c7',
          border: '2px dashed #f59e0b',
          borderRadius: '12px',
          display: 'inline-block',
        }}
      >
        <p style={{ margin: 0, fontSize: '14px' }}>
          <strong>⚠️ 温馨提示：</strong>
          <br />
          前方可能有<b>乱飞的代码</b>、<b>滚动的bug</b>和<b>飘散的咖啡香</b>
          <br />
          建议先来杯奶茶，耐心等待片刻哦～
        </p>
      </div>

      {/* 点击跳转彩蛋（跳回 Dashboard） */}
      <div style={{ marginTop: '30px', fontSize: '12px', color: '#9ca3af' }}>
        <span
          onClick={goDashboard}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') goDashboard();
          }}
          style={{
            cursor: 'pointer',
            borderBottom: '1px dotted #9ca3af',
            position: 'relative',
            display: 'inline-block',
            padding: '2px 4px',
          }}
          title="点击返回仪表盘"
          className="easter-egg"
        >
          悄悄告诉你：点击这里会发现...
          <span
            className="easter-tooltip"
            style={{
              position: 'absolute',
              bottom: '130%',
              left: '50%',
              transform: 'translateX(-50%)',
              background: '#1f2937',
              color: 'white',
              padding: '8px 10px',
              borderRadius: '6px',
              fontSize: '11px',
              whiteSpace: 'nowrap',
              opacity: 0,
              transition: 'opacity 0.2s',
              pointerEvents: 'none',
            }}
          >
            程序员说：再催就给你写bug！
          </span>
        </span>
      </div>

      {/* 注意：这里不要用 style jsx（Vite/CRA 默认不支持）。
          用普通 <style> 才会生效 */}
      <style>{`
        @keyframes bounce {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-20px); }
        }
        @keyframes shimmer {
          0% { filter: brightness(1); }
          50% { filter: brightness(1.15); }
          100% { filter: brightness(1); }
        }
        .easter-egg:hover .easter-tooltip {
          opacity: 1;
        }
      `}</style>
    </div>
  );
}
