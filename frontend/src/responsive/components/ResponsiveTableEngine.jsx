import { useResponsive } from '../hooks/useResponsive';
import { cn } from '../../utils/cn';

/**
 * Adaptive table → card conversion on mobile without changing desktop tables.
 */
export function ResponsiveTableEngine({
  columns = [],
  rows = [],
  renderCard,
  className,
  tableClassName,
}) {
  const { isDesktop } = useResponsive();

  if (isDesktop) {
    return (
      <div className={cn('responsive-table-desktop overflow-x-auto', className)}>
        <table className={cn('w-full text-sm', tableClassName)}>
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col.key} className="text-left py-2 px-2 text-gray-500 font-medium text-xs">
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={row.id ?? i} className="border-t border-edge/5">
                {columns.map((col) => (
                  <td key={col.key} className="py-2 px-2 text-heading tabular-nums">
                    {col.render ? col.render(row) : row[col.key]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className={cn('responsive-table-mobile flex flex-col gap-2', className)}>
      {rows.map((row, i) => (
        <div
          key={row.id ?? i}
          className="responsive-table-card rounded-xl border border-edge/10 bg-surface-800/40 p-3"
        >
          {renderCard ? renderCard(row) : (
            <dl className="grid grid-cols-2 gap-2 text-xs">
              {columns.map((col) => (
                <div key={col.key}>
                  <dt className="text-gray-500">{col.label}</dt>
                  <dd className="text-heading font-mono tabular-nums">
                    {col.render ? col.render(row) : row[col.key]}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      ))}
    </div>
  );
}

export default ResponsiveTableEngine;
