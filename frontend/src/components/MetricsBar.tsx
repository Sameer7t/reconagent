import React from 'react';
import { Files, CheckCircle2, AlertTriangle, Clock } from 'lucide-react';
import { MetricCounts } from '../types';

interface MetricsBarProps {
  metrics: MetricCounts;
  activeFilter?: string;
  onFilterSelect: (filter: string) => void;
}

export const MetricsBar: React.FC<MetricsBarProps> = ({
  metrics,
  activeFilter,
  onFilterSelect,
}) => {
  const cards = [
    {
      id: 'ALL',
      label: 'Total Cases',
      value: metrics.total_cases,
      icon: Files,
      color: 'text-slate-200',
      bg: 'bg-slate-800/60',
      border: 'border-slate-700/80',
      glow: 'hover:border-slate-500',
      activeRing: activeFilter === 'ALL' ? 'ring-2 ring-sky-500/50' : '',
    },
    {
      id: 'MATCHED',
      label: 'Matched Clean',
      value: metrics.matched,
      icon: CheckCircle2,
      color: 'text-emerald-400',
      bg: 'bg-emerald-950/20',
      border: 'border-emerald-800/40',
      glow: 'hover:border-emerald-500/60',
      activeRing: activeFilter === 'MATCHED' ? 'ring-2 ring-emerald-500/50' : '',
    },
    {
      id: 'DISCREPANCIES',
      label: 'Discrepancies',
      value: metrics.discrepancies,
      icon: AlertTriangle,
      color: 'text-amber-400',
      bg: 'bg-amber-950/20',
      border: 'border-amber-800/40',
      glow: 'hover:border-amber-500/60',
      activeRing: activeFilter === 'DISCREPANCIES' ? 'ring-2 ring-amber-500/50' : '',
    },
    {
      id: 'UNDER_REVIEW',
      label: 'Under Review',
      value: metrics.under_review,
      icon: Clock,
      color: 'text-sky-400',
      bg: 'bg-sky-950/20',
      border: 'border-sky-800/40',
      glow: 'hover:border-sky-500/60',
      activeRing: activeFilter === 'UNDER_REVIEW' ? 'ring-2 ring-sky-500/50' : '',
    },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 sm:gap-3 mb-2.5 sm:mb-3 flex-shrink-0">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <button
            key={card.id}
            onClick={() => onFilterSelect(card.id)}
            className={`text-left p-2.5 sm:p-3 rounded-xl ${card.bg} border ${card.border} ${card.glow} ${card.activeRing} transition duration-150 shadow-sm cursor-pointer group`}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="text-[11px] sm:text-xs font-medium text-slate-400 group-hover:text-slate-300 truncate">
                {card.label}
              </span>
              <Icon className={`w-3.5 h-3.5 sm:w-4 sm:h-4 ${card.color} flex-shrink-0 ml-1`} />
            </div>
            <div className="flex items-baseline space-x-1.5 sm:space-x-2">
              <span className="text-lg sm:text-xl font-bold tracking-tight text-white">
                {card.value.toLocaleString()}
              </span>
              <span className="text-[10px] sm:text-[11px] text-slate-500">cases</span>
            </div>
          </button>
        );
      })}
    </div>
  );
};
