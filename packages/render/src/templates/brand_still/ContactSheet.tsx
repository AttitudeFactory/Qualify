// Spike m-25042530: a labelled contact sheet (rows × columns of images), composed in Remotion so
// the overview images follow the house rule (composition only in Remotion).
import React from 'react';
import {AbsoluteFill, Img, type CalculateMetadataFunction} from 'remotion';
import {asset} from './BrandStill';

export type SheetProps = {
  title: string;
  subtitle?: string;
  cell: {w: number; h: number};
  columns: string[];
  rows: Array<{label: string; note?: string; cells: Array<{src: string | null; caption?: string; cellH?: number} | null>}>;
};

const PAD = 28;
const HEAD = 150;
const ROW_LABEL = 230;
const COL_HEAD = 54;
const CAPTION = 40;

const rowHeight = (p: SheetProps, r: SheetProps['rows'][number]): number =>
  Math.max(...r.cells.map((c) => (c?.cellH ?? p.cell.h))) + CAPTION + PAD;

export const sheetMetadata: CalculateMetadataFunction<SheetProps> = ({props}) => ({
  width: PAD * 2 + ROW_LABEL + props.columns.length * (props.cell.w + PAD),
  height: HEAD + COL_HEAD + props.rows.reduce((a, r) => a + rowHeight(props, r), 0) + PAD,
});

export const ContactSheet: React.FC<SheetProps> = (p) => {
  let y = HEAD + COL_HEAD;
  return (
    <AbsoluteFill style={{background: '#f4f1ea', fontFamily: 'Helvetica, Arial, sans-serif', color: '#1d1d1f'}}>
      <div style={{position: 'absolute', left: PAD, top: 30, fontSize: 46, fontWeight: 800}}>{p.title}</div>
      {p.subtitle ? <div style={{position: 'absolute', left: PAD, top: 92, fontSize: 24, color: '#555'}}>{p.subtitle}</div> : null}
      {p.columns.map((c, i) => (
        <div key={i} style={{position: 'absolute', left: PAD + ROW_LABEL + i * (p.cell.w + PAD), top: HEAD, width: p.cell.w, fontSize: 24, fontWeight: 700}}>
          {c}
        </div>
      ))}
      {p.rows.map((r, ri) => {
        const top = y;
        y += rowHeight(p, r);
        return (
          <React.Fragment key={ri}>
            <div style={{position: 'absolute', left: PAD, top, width: ROW_LABEL - 20, fontSize: 26, fontWeight: 800, lineHeight: 1.2}}>
              {r.label}
              {r.note ? <div style={{fontSize: 19, fontWeight: 400, color: '#555', marginTop: 10, lineHeight: 1.3}}>{r.note}</div> : null}
            </div>
            {r.cells.map((c, ci) => {
              const left = PAD + ROW_LABEL + ci * (p.cell.w + PAD);
              if (!c) return null;
              const h = c.cellH ?? p.cell.h;
              return (
                <React.Fragment key={ci}>
                  {c.src ? (
                    <Img src={asset(c.src)} style={{position: 'absolute', left, top, width: p.cell.w, height: h, objectFit: 'contain', background: '#ddd', boxShadow: '0 4px 14px #0003'}} />
                  ) : (
                    <div style={{position: 'absolute', left, top, width: p.cell.w, height: h, background: '#e5e1d8', display: 'grid', placeItems: 'center', fontSize: 22, color: '#777'}}>sin imagen</div>
                  )}
                  {c.caption ? <div style={{position: 'absolute', left, top: top + h + 8, width: p.cell.w, fontSize: 19, color: '#333'}}>{c.caption}</div> : null}
                </React.Fragment>
              );
            })}
          </React.Fragment>
        );
      })}
    </AbsoluteFill>
  );
};
