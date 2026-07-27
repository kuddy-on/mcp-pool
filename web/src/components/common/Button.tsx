import React from 'react';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'small' | 'danger-small';
  children: React.ReactNode;
}

export const Button: React.FC<ButtonProps> = ({
  variant = 'secondary',
  children,
  style,
  disabled,
  ...props
}) => {
  const baseStyle: React.CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '6px',
    borderRadius: '6px',
    fontSize: '12px',
    fontWeight: 600,
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.6 : 1,
    transition: 'all 0.15s ease',
    outline: 'none',
    border: 'none',
  };

  const variantStyles: Record<string, React.CSSProperties> = {
    primary: {
      backgroundColor: '#4f46e5',
      color: '#ffffff',
      padding: '8px 14px',
      boxShadow: '0 1px 2px rgba(79,70,229,0.2)',
    },
    secondary: {
      backgroundColor: '#ffffff',
      color: '#334155',
      border: '1px solid #cbd5e1',
      padding: '7px 12px',
    },
    danger: {
      backgroundColor: '#ef4444',
      color: '#ffffff',
      padding: '8px 14px',
    },
    small: {
      backgroundColor: '#ffffff',
      color: '#475569',
      border: '1px solid #cbd5e1',
      padding: '4px 8px',
      fontSize: '11px',
    },
    'danger-small': {
      backgroundColor: '#ffffff',
      color: '#ef4444',
      border: '1px solid #fca5a5',
      padding: '4px 8px',
      fontSize: '11px',
    },
  };

  return (
    <button
      style={{
        ...baseStyle,
        ...variantStyles[variant],
        ...style,
      }}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  );
};
