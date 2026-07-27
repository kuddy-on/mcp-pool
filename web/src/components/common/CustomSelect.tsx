import React, { useState, useRef, useEffect } from 'react';
import { ChevronDown } from 'lucide-react';

export interface SelectOption {
  label: string;
  value: string;
}

export interface CustomSelectProps {
  options: SelectOption[];
  value: string;
  onChange: (val: string) => void;
  style?: React.CSSProperties;
  placeholder?: string;
}

export const CustomSelect: React.FC<CustomSelectProps> = ({
  options,
  value,
  onChange,
  style,
  placeholder,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [hoveredValue, setHoveredValue] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const selectedOption = options.find((o) => o.value === value);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div ref={containerRef} style={{ position: 'relative', display: 'inline-block', ...style }}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '8px',
          padding: '6px 12px',
          borderRadius: '6px',
          border: '1px solid #cbd5e1',
          backgroundColor: '#ffffff',
          color: selectedOption ? '#0f172a' : '#94a3b8',
          fontSize: '12px',
          fontWeight: 500,
          cursor: 'pointer',
          width: '100%',
          boxSizing: 'border-box',
          outline: 'none',
        }}
      >
        <span>{selectedOption ? selectedOption.label : placeholder || 'Select...'}</span>
        <ChevronDown size={14} color="#64748b" />
      </button>

      {isOpen && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            marginTop: '4px',
            backgroundColor: '#ffffff',
            border: '1px solid #e2e8f0',
            borderRadius: '6px',
            boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
            zIndex: 1000,
            maxHeight: '200px',
            overflowY: 'auto',
            padding: '4px',
          }}
        >
          {options.map((opt) => (
            <div
              key={opt.value}
              onClick={() => {
                onChange(opt.value);
                setIsOpen(false);
              }}
              onMouseEnter={() => setHoveredValue(opt.value)}
              onMouseLeave={() => setHoveredValue(null)}
              style={{
                padding: '6px 10px',
                fontSize: '12px',
                borderRadius: '4px',
                cursor: 'pointer',
                backgroundColor:
                  opt.value === value
                    ? '#f1f5f9'
                    : hoveredValue === opt.value
                    ? '#f8fafc'
                    : 'transparent',
                color: opt.value === value ? '#4f46e5' : '#1e293b',
                fontWeight: opt.value === value ? 600 : 400,
              }}
            >
              {opt.label}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
