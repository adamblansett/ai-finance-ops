import { useState } from 'react';
import { FileUp, FileSpreadsheet } from 'lucide-react';
import { ingestInlinePayload, uploadDocumentFile } from '../api/client';
import type { ActorContext, DocType, IngestedDocument } from '../types/finance';
import { StatusBadge } from './StatusBadge';

interface IngestionViewProps {
  actor: ActorContext;
  documents: IngestedDocument[];
  onRefresh: () => Promise<void>;
  onNotify: (msg: string, isError?: boolean) => void;
}

const SAMPLE_INVOICE_JSON = JSON.stringify(
  [
    {
      invoice_number: 'INV-SAMPLE-901',
      direction: 'payable',
      counterparty_name: 'CloudCore Infrastructure LLC',
      po_number: 'PO-2026-1001',
      subtotal: 24000.0,
      tax_amount: 0.0,
      total_amount: 24000.0,
      line_items: [{ sku: 'GPU-NODE-X', qty: 10, unit_price: 2400.0 }],
    },
  ],
  null,
  2,
);

export function IngestionView({
  actor,
  documents,
  onRefresh,
  onNotify,
}: IngestionViewProps) {
  const [docType, setDocType] = useState<DocType>('invoice');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [autoReconcile, setAutoReconcile] = useState(true);
  const [inlineFilename, setInlineFilename] = useState('sample-invoice-batch.json');
  const [inlineFormat, setInlineFormat] = useState<'json' | 'csv'>('json');
  const [inlineContent, setInlineContent] = useState(SAMPLE_INVOICE_JSON);
  const [submitting, setSubmitting] = useState(false);

  async function handleFileUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedFile) {
      onNotify('Choose a CSV, JSON, or PDF file first.', true);
      return;
    }
    setSubmitting(true);
    try {
      const res = await uploadDocumentFile(actor, selectedFile, docType, autoReconcile);
      onNotify(res.message);
      setSelectedFile(null);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Upload failed', true);
      await onRefresh();
    } finally {
      setSubmitting(false);
    }
  }

  async function handleInlineIngest(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      const res = await ingestInlinePayload(actor, {
        filename: inlineFilename,
        doc_type: docType,
        format: inlineFormat,
        content: inlineContent,
        auto_reconcile: autoReconcile,
      });
      onNotify(res.message);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Inline ingestion failed', true);
      await onRefresh();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-2">
        <form
          onSubmit={handleFileUpload}
          className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-4"
        >
          <div className="flex items-center gap-2">
            <FileUp className="h-4 w-4 text-indigo-600" />
            <h2 className="text-sm font-semibold text-slate-900">
              Upload Document (PDF / CSV / JSON / OFX)
            </h2>
          </div>
          <p className="text-xs text-slate-600">
            Supports QBO/Xero/NetSuite CSVs, OFX/QFX bank feeds, PDF invoices, and JSON.
            Every file is fingerprinted with SHA-256; duplicates return HTTP 409.
          </p>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-xs font-medium text-slate-700">
              Document Type
              <select
                value={docType}
                onChange={(e) => setDocType(e.target.value as DocType)}
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs"
              >
                <option value="invoice">Invoice (AP/AR)</option>
                <option value="purchase_order">Purchase Order</option>
                <option value="goods_receipt">Goods Receipt</option>
                <option value="bank_statement">Bank Statement</option>
                <option value="expense">Expense Batch</option>
              </select>
            </label>

            <label className="flex items-center gap-2 pt-5 text-xs font-medium text-slate-700">
              <input
                type="checkbox"
                checked={autoReconcile}
                onChange={(e) => setAutoReconcile(e.target.checked)}
                className="rounded border-slate-300 text-indigo-600"
              />
              Auto-run 3-way match on invoices
            </label>
          </div>

          <label className="block text-xs font-medium text-slate-700">
            Select File
            <input
              type="file"
              accept=".csv,.json,.pdf,.ofx,.qfx"
              onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
              className="mt-1 block w-full text-xs text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-indigo-50 file:px-3 file:py-1.5 file:text-xs file:font-semibold file:text-indigo-700 hover:file:bg-indigo-100"
            />
          </label>

          <button
            type="submit"
            disabled={submitting}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {submitting ? 'Ingesting...' : 'Upload & Parse Document'}
          </button>
        </form>

        <form
          onSubmit={handleInlineIngest}
          className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-3"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileSpreadsheet className="h-4 w-4 text-indigo-600" />
              <h2 className="text-sm font-semibold text-slate-900">
                Inline Payload &amp; Duplicate-Hash Tester
              </h2>
            </div>
            <span className="text-[11px] text-slate-500">
              Submit twice to verify SHA-256 block
            </span>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-xs font-medium text-slate-700">
              Virtual Filename
              <input
                type="text"
                value={inlineFilename}
                onChange={(e) => setInlineFilename(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
              />
            </label>
            <label className="block text-xs font-medium text-slate-700">
              Format
              <select
                value={inlineFormat}
                onChange={(e) => setInlineFormat(e.target.value as 'json' | 'csv')}
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs"
              >
                <option value="json">JSON</option>
                <option value="csv">CSV</option>
              </select>
            </label>
          </div>

          <textarea
            rows={6}
            value={inlineContent}
            onChange={(e) => setInlineContent(e.target.value)}
            className="w-full rounded-lg border border-slate-300 bg-slate-50 p-2.5 font-mono text-[11px]"
          />

          <button
            type="submit"
            disabled={submitting}
            className="rounded-lg bg-slate-900 px-4 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
          >
            Ingest Inline Payload
          </button>
        </form>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
        <div className="border-b border-slate-200 px-5 py-3.5">
          <h2 className="text-sm font-semibold text-slate-900">
            Ingested Documents &amp; SHA-256 Registry ({documents.length})
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-xs">
            <thead className="bg-slate-50 text-left text-[11px] font-semibold uppercase text-slate-500">
              <tr>
                <th className="px-4 py-2.5">Filename</th>
                <th className="px-4 py-2.5">Type</th>
                <th className="px-4 py-2.5">SHA-256</th>
                <th className="px-4 py-2.5">Records</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5">Uploaded By</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {documents.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-slate-500">
                    No uploaded documents yet. Upload a CSV/JSON/PDF or ingest the sample payload
                    above.
                  </td>
                </tr>
              ) : (
                documents.map((doc) => (
                  <tr key={doc.id}>
                    <td className="px-4 py-2.5 font-medium text-slate-900">{doc.filename}</td>
                    <td className="px-4 py-2.5 text-slate-600">{doc.doc_type}</td>
                    <td className="px-4 py-2.5 font-mono text-[11px] text-slate-500">
                      {doc.content_sha256.slice(0, 14)}...
                    </td>
                    <td className="px-4 py-2.5">{doc.parsed_records_count}</td>
                    <td className="px-4 py-2.5">
                      <StatusBadge status={doc.status} />
                    </td>
                    <td className="px-4 py-2.5 text-slate-600">{doc.uploaded_by}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
