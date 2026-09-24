import React from 'react';
import { Scale, CheckCircle2, AlertTriangle, XCircle } from 'lucide-react';
import { ThreeWayMatchData } from '../types';

interface ThreeWayMatchCardProps {
  data: ThreeWayMatchData;
}

export const ThreeWayMatchCard: React.FC<ThreeWayMatchCardProps> = ({ data }) => {
  const isMatch = data.match_status === 'MATCHED';
  const isPriceMismatch = data.match_status === 'PRICE_MISMATCH';
  const isQtyMismatch = data.match_status === 'QUANTITY_MISMATCH';
  const isCalcError = data.match_status === 'CALCULATION_ERROR';

  // Format currency
  const fmtCurrency = (val: number | null) => {
    if (val === null || val === undefined) return '-';
    return `$${val.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  const fmtQty = (val: number | null) => {
    if (val === null || val === undefined) return '-';
    return val.toString();
  };

  return (
    <div className="bg-slate-850 rounded-xl border border-slate-700/80 p-4 sm:p-5 shadow-lg relative overflow-hidden">
      {/* Accent strip */}
      <div
        className={`absolute top-0 left-0 right-0 h-1 ${
          isMatch
            ? 'bg-emerald-500'
            : isPriceMismatch
            ? 'bg-amber-500'
            : 'bg-rose-500'
        }`}
      />

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 sm:gap-3 mb-3 sm:mb-4 pb-3 border-b border-slate-700/60">
        <div className="flex items-center space-x-2.5">
          <div className="p-1.5 sm:p-2 rounded-lg bg-sky-500/10 text-sky-400 border border-sky-500/20 flex-shrink-0">
            <Scale className="w-4 h-4 sm:w-5 sm:h-5" />
          </div>
          <div>
            <h3 className="font-bold text-slate-100 tracking-wide text-xs sm:text-sm uppercase flex items-center gap-2">
              Three-Way Match Comparison
            </h3>
            <p className="text-[11px] sm:text-xs text-slate-400">
              Deterministic reconciliation: Purchase Order vs Invoice vs Receipt
            </p>
          </div>
        </div>

        {/* Status Badge */}
        <div className="self-start sm:self-auto">
          {isMatch ? (
            <span className="inline-flex items-center gap-1.5 px-2.5 sm:px-3 py-1 rounded-full text-[11px] sm:text-xs font-semibold bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 whitespace-nowrap">
              <CheckCircle2 className="w-3.5 h-3.5 flex-shrink-0" />
              MATCHED PERFECTLY
            </span>
          ) : isPriceMismatch ? (
            <span className="inline-flex items-center gap-1.5 px-2.5 sm:px-3 py-1 rounded-full text-[11px] sm:text-xs font-semibold bg-amber-500/10 text-amber-300 border border-amber-500/30 whitespace-nowrap">
              <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
              {data.mismatch_badge || '⚠ PRICE MISMATCH'}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 px-2.5 sm:px-3 py-1 rounded-full text-[11px] sm:text-xs font-semibold bg-rose-500/10 text-rose-300 border border-rose-500/30 whitespace-nowrap">
              <XCircle className="w-3.5 h-3.5 flex-shrink-0" />
              {data.mismatch_badge || '⚠ DISCREPANCY FLAGGED'}
            </span>
          )}
        </div>
      </div>

      {/* Side-by-Side Comparison Table (Fits 100% width without horizontal scrolling) */}
      <div className="overflow-hidden">
        <table className="w-full text-left border-collapse table-fixed">
          <colgroup>
            <col className="w-[28%]" />
            <col className="w-[24%]" />
            <col className="w-[24%]" />
            <col className="w-[24%]" />
          </colgroup>
          <thead>
            <tr className="border-b border-slate-700/80 text-[10px] sm:text-xs uppercase tracking-wider text-slate-400">
              <th className="py-2 px-1.5 sm:px-3 font-semibold truncate">Metric</th>
              <th className="py-2 px-1.5 sm:px-3 font-semibold text-right bg-slate-800/30 rounded-t truncate">
                <span className="text-sky-300 font-bold">PO</span>
                <span className="block text-[9px] text-slate-400 font-normal truncate">
                  {data.po_id || '-'}
                </span>
              </th>
              <th className="py-2 px-1.5 sm:px-3 font-semibold text-right bg-slate-800/50 rounded-t truncate">
                <span className="text-indigo-300 font-bold">Invoice</span>
                <span className="block text-[9px] text-slate-400 font-normal truncate">
                  {data.invoice_id || '-'}
                </span>
              </th>
              <th className="py-2 px-1.5 sm:px-3 font-semibold text-right bg-slate-800/30 rounded-t truncate">
                <span className="text-emerald-300 font-bold">Receipt</span>
                <span className="block text-[9px] text-slate-400 font-normal truncate">
                  {data.receipt_id || '-'}
                </span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 font-mono text-[11px] sm:text-xs">
            {!data.lines || data.lines.length === 0 ? (
              <tr>
                <td colSpan={4} className="py-8 text-center text-slate-400 font-sans text-xs">
                  No line item comparison records available for this case. Upload documents to reconcile.
                </td>
              </tr>
            ) : (
              data.lines.map((line, idx) => {
                const hasPriceVar =
                  line.po_unit_price !== null &&
                  line.invoice_unit_price !== null &&
                  line.po_unit_price !== line.invoice_unit_price;
                const hasQtyVar =
                  line.invoice_quantity !== null &&
                  line.receipt_quantity !== null &&
                  line.invoice_quantity !== line.receipt_quantity;

                const hasRcptPriceVar =
                  line.receipt_unit_price !== null &&
                  ((line.po_unit_price !== null && Math.abs(line.receipt_unit_price - line.po_unit_price) > 0.01) ||
                   (line.invoice_unit_price !== null && Math.abs(line.receipt_unit_price - line.invoice_unit_price) > 0.01));

                const hasRcptTotVar =
                  line.receipt_total !== null &&
                  ((line.po_total !== null && Math.abs(line.receipt_total - line.po_total) > 0.01) ||
                   (line.invoice_total !== null && Math.abs(line.receipt_total - line.invoice_total) > 0.01));

                return (
                <React.Fragment key={idx}>
                  {/* Item Description row if multi-line */}
                  <tr className="bg-slate-900/40 text-slate-300">
                    <td colSpan={4} className="py-1 px-1.5 sm:px-3 text-[10px] sm:text-[11px] font-sans font-medium text-slate-400 truncate">
                      Line {line.line_number}: <span className="text-slate-200">{line.description}</span>
                    </td>
                  </tr>

                  {/* Quantity row */}
                  <tr className="hover:bg-slate-800/40 transition">
                    <td className="py-1.5 px-1.5 sm:px-3 text-slate-400 font-sans truncate">Quantity</td>
                    <td className="py-1.5 px-1.5 sm:px-3 text-right text-slate-200 truncate">{fmtQty(line.po_quantity)}</td>
                    <td
                      className={`py-1.5 px-1.5 sm:px-3 text-right truncate ${
                        hasQtyVar ? 'text-rose-400 font-bold bg-rose-500/10' : 'text-slate-200'
                      }`}
                    >
                      {fmtQty(line.invoice_quantity)}
                    </td>
                    <td className="py-1.5 px-1.5 sm:px-3 text-right text-slate-200 truncate">{fmtQty(line.receipt_quantity)}</td>
                  </tr>

                  {/* Unit Price row */}
                  <tr className="hover:bg-slate-800/40 transition">
                    <td className="py-1.5 px-1.5 sm:px-3 text-slate-400 font-sans truncate">Unit Price</td>
                    <td className="py-1.5 px-1.5 sm:px-3 text-right text-slate-200 truncate">{fmtCurrency(line.po_unit_price)}</td>
                    <td
                      className={`py-1.5 px-1.5 sm:px-3 text-right truncate ${
                        hasPriceVar ? 'text-amber-400 font-bold bg-amber-500/10' : 'text-slate-200'
                      }`}
                    >
                      {fmtCurrency(line.invoice_unit_price)}
                    </td>
                    <td
                      className={`py-1.5 px-1.5 sm:px-3 text-right truncate ${
                        hasRcptPriceVar
                          ? 'text-amber-400 font-bold bg-amber-500/10'
                          : line.receipt_unit_price !== null
                          ? 'text-slate-200'
                          : 'text-slate-500'
                      }`}
                    >
                      {line.receipt_unit_price !== null ? (
                        fmtCurrency(line.receipt_unit_price)
                      ) : (
                        <span className="text-slate-500">-</span>
                      )}
                    </td>
                  </tr>

                  {/* Line Total row */}
                  <tr className="hover:bg-slate-800/40 transition font-semibold">
                    <td className="py-1.5 px-1.5 sm:px-3 text-slate-400 font-sans truncate">Line Total</td>
                    <td className="py-1.5 px-1.5 sm:px-3 text-right text-slate-100 truncate">{fmtCurrency(line.po_total)}</td>
                    <td
                      className={`py-1.5 px-1.5 sm:px-3 text-right truncate ${
                        hasPriceVar || hasQtyVar ? 'text-amber-300 bg-amber-500/10' : 'text-slate-100'
                      }`}
                    >
                      {fmtCurrency(line.invoice_total)}
                    </td>
                    <td
                      className={`py-1.5 px-1.5 sm:px-3 text-right truncate ${
                        hasRcptTotVar
                          ? 'text-amber-300 bg-amber-500/10'
                          : line.receipt_total !== null
                          ? 'text-slate-100'
                          : 'text-slate-500'
                      }`}
                    >
                      {line.receipt_total !== null ? (
                        fmtCurrency(line.receipt_total)
                      ) : (
                        <span className="text-slate-500">-</span>
                      )}
                    </td>
                  </tr>
                </React.Fragment>
              );
            })
          )}

            {/* Grand Totals */}
            <tr className="border-t-2 border-slate-700 bg-slate-800/40 font-bold text-xs">
              <td className="py-2 px-1.5 sm:px-3 text-white font-sans truncate">Total</td>
              <td className="py-2 px-1.5 sm:px-3 text-right text-sky-300 truncate">{fmtCurrency(data.total_po)}</td>
              <td className={`py-2 px-1.5 sm:px-3 text-right truncate ${!isMatch ? 'text-amber-400' : 'text-emerald-300'}`}>
                {fmtCurrency(data.total_invoice)}
              </td>
              <td
                className={`py-2 px-1.5 sm:px-3 text-right truncate ${
                  (data.total_receipt > 0 &&
                  ((data.total_po > 0 && Math.abs(data.total_receipt - data.total_po) > 0.01) ||
                   (data.total_invoice > 0 && Math.abs(data.total_receipt - data.total_invoice) > 0.01))) ||
                  isCalcError
                    ? 'text-amber-400 font-bold'
                    : data.total_receipt > 0
                    ? 'text-emerald-300'
                    : 'text-slate-500 font-mono text-[11px]'
                }`}
                title={
                  isCalcError
                    ? 'Internal document arithmetic validation discrepancy detected'
                    : data.total_receipt > 0
                    ? 'Receipt total amount'
                    : 'Delivery receipts verify physical quantities delivered; monetary amounts optional'
                }
              >
                {data.total_receipt > 0 ? (
                  fmtCurrency(data.total_receipt)
                ) : (
                  <span className="text-slate-500">-</span>
                )}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* Prominent Mismatch Callout */}
      {!isMatch && (
        <div className="mt-3 sm:mt-4 p-2.5 sm:p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs">
          <div className="flex items-start sm:items-center space-x-2 text-amber-300 font-medium">
            <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5 sm:mt-0" />
            <span>
              {data.mismatch_badge || '⚠ PRICE MISMATCH'}: Variance of {fmtCurrency(Math.abs(data.difference_amount))} ({data.difference_percent.toFixed(1)}%) detected between PO and billed Invoice.
            </span>
          </div>
          <div className="text-[11px] font-mono text-amber-400 font-bold bg-amber-950/40 px-2 py-0.5 rounded border border-amber-500/20 self-start sm:self-auto flex-shrink-0">
            Diff: {data.difference_amount >= 0 ? `+${fmtCurrency(data.difference_amount)}` : `-${fmtCurrency(Math.abs(data.difference_amount))}`}
          </div>
        </div>
      )}
    </div>
  );
};
