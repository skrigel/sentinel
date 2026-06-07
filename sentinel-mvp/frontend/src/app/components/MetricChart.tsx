import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts';
import { MetricDataPoint, MetricType } from '../types';

interface MetricChartProps {
  data: MetricDataPoint[];
  type: MetricType;
  status: 'healthy' | 'warning' | 'critical' | 'recovering';
  label?: string;
  /** Override the unit (defaults to MB for memory, % otherwise). */
  unit?: string;
  /** Decimal places for the value readout/tooltip (default 1). */
  precision?: number;
}

export function MetricChart({ data, type, status, label, unit: unitProp, precision = 1 }: MetricChartProps) {
  const formatTime = (timestamp: number) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    });
  };

  const getStrokeColor = () => {
    if (status === 'healthy') return '#10b981';
    if (status === 'warning') return '#f59e0b';
    if (status === 'critical') return '#ef4444';
    return '#3b82f6';
  };

  const round = Math.pow(10, precision);
  const chartData = data.map(d => ({
    time: d.timestamp,
    value: Math.round(d.value * round) / round,
  }));

  const currentValue = chartData[chartData.length - 1]?.value || 0;
  const unit = unitProp ?? (type === 'memory' ? 'MB' : '%');

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <div>
          <div className="text-xs font-medium text-gray-500 uppercase tracking-wide">
            {label ?? (type === 'memory' ? 'Memory' : 'CPU')}
          </div>
          <div className="text-2xl font-light text-gray-900 mt-1">
            {currentValue.toFixed(precision)}
            <span className="text-base text-gray-400 ml-1">{unit}</span>
          </div>
        </div>
        <div className={`text-xs font-medium px-2 py-1 rounded ${
          status === 'healthy' ? 'bg-green-50 text-green-700' :
          status === 'warning' ? 'bg-amber-50 text-amber-700' :
          status === 'critical' ? 'bg-red-50 text-red-700' :
          'bg-blue-50 text-blue-700'
        }`}>
          {status}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={120}>
        <LineChart data={chartData} margin={{ top: 5, right: 0, left: 0, bottom: 5 }}>
          <XAxis
            dataKey="time"
            tickFormatter={formatTime}
            stroke="#d1d5db"
            tick={{ fill: '#9ca3af', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            stroke="#d1d5db"
            tick={{ fill: '#9ca3af', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={40}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: '#ffffff',
              border: '1px solid #e5e7eb',
              borderRadius: '6px',
              fontSize: '12px',
            }}
            labelFormatter={formatTime}
            formatter={(value: number) => [
              `${value.toFixed(precision)}${unit}`,
              label ?? (type === 'memory' ? 'Memory' : 'CPU'),
            ]}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke={getStrokeColor()}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
