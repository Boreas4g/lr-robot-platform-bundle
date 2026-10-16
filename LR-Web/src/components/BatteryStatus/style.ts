import { createStyles } from 'antd-style';

export const useStyles = createStyles(({ token }) => ({
  badge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 5,
    flexShrink: 0,
    height: 22,
    padding: '0 2px',
    border: 0,
    borderRadius: 4,
    background: 'transparent',
    color: token.colorTextSecondary,
    cursor: 'pointer',
    fontSize: 12,
    lineHeight: 1,
    fontVariantNumeric: 'tabular-nums',
    whiteSpace: 'nowrap',
    '&:hover': { background: token.colorFillTertiary, color: token.colorText },
    '&:focus-visible': {
      outline: '2px solid ' + token.colorPrimary,
      outlineOffset: 2,
    },
  },
}));
