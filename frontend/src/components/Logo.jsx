export const Logo = ({ size = 34 }) => (
  <svg width={size} height={size} viewBox="0 0 40 40" role="img" aria-label="InvestWatch" data-testid="app-logo-svg">
    <rect x="1" y="1" width="38" height="38" rx="3" fill="#0B192C" stroke="#2E5077" strokeWidth="1.5" />
    <polyline points="5,31 11,26 16,28 21,20 27,23 35,10" fill="none" stroke="#64748B" strokeWidth="1.6" strokeLinejoin="round" />
    <circle cx="19" cy="18" r="8.5" fill="#0B192C" stroke="#FFFFFF" strokeWidth="2" />
    <path d="M12.5 18 Q19 11.8 25.5 18 Q19 24.2 12.5 18Z" fill="#FFFFFF" />
    <circle cx="19" cy="18" r="2.4" fill="#D97706" />
    <line x1="25.2" y1="24.2" x2="32" y2="31" stroke="#FFFFFF" strokeWidth="2.8" strokeLinecap="round" />
  </svg>
);
