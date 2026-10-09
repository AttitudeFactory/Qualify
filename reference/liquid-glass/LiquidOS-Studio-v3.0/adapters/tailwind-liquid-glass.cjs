const plugin = require('tailwindcss/plugin');

module.exports = plugin(({ addComponents, addUtilities, theme }) => {
  addComponents({
    '.lq-glass': {
      position: 'relative',
      isolation: 'isolate',
      overflow: 'hidden',
      border: '1px solid rgba(255,255,255,.18)',
      borderRadius: theme('borderRadius.2xl', '1.25rem'),
      background: 'linear-gradient(145deg,rgba(255,255,255,.11),rgba(255,255,255,.025)),rgba(8,12,24,.2)',
      boxShadow: 'inset 0 1px 0 rgba(255,255,255,.16),0 14px 36px rgba(0,0,0,.18)',
      backdropFilter: 'blur(24px) saturate(150%)'
    },
    '.lq-glass-clear': {
      background: 'linear-gradient(145deg,rgba(255,255,255,.075),rgba(255,255,255,.018))',
      borderColor: 'rgba(255,255,255,.25)',
      backdropFilter: 'blur(10px) saturate(150%)'
    },
    '.lq-glass-frosted': {
      background: 'linear-gradient(145deg,rgba(255,255,255,.17),rgba(255,255,255,.045))',
      backdropFilter: 'blur(34px) saturate(135%)'
    },
    '.lq-glass-liquid': {
      background: 'radial-gradient(75% 110% at 8% 0%,rgba(255,255,255,.18),transparent 42%),linear-gradient(130deg,rgba(255,255,255,.105),rgba(255,255,255,.022) 55%,rgba(139,124,255,.075))',
      borderColor: 'rgba(255,255,255,.27)',
      backdropFilter: 'blur(18px) saturate(178%)'
    }
  });

  addUtilities({
    '.lq-backdrop-clear': { backdropFilter: 'blur(10px) saturate(150%)' },
    '.lq-backdrop-liquid': { backdropFilter: 'blur(18px) saturate(178%)' },
    '.lq-backdrop-frosted': { backdropFilter: 'blur(34px) saturate(135%)' },
    '.lq-edge-bright': { borderColor: 'rgba(255,255,255,.3)' },
    '.lq-edge-soft': { borderColor: 'rgba(255,255,255,.12)' }
  });
});
