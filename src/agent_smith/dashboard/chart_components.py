"""
Chart creation and visualization components for the dashboard.
"""

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from loguru import logger

from agent_smith.exceptions import ValidationException


class ChartManager:
    """Manages chart creation and visualization for the dashboard."""
    
    def __init__(self):
        self.chart_config = {
            'height': 400,
            'margin': dict(l=50, r=50, t=50, b=50),
            'template': 'plotly_white'
        }
        
    def create_pnl_chart(self, trades_df: pd.DataFrame) -> go.Figure:
        """Create PnL performance chart from trades data."""
        try:
            if trades_df.empty:
                return self._create_empty_chart("No trade data available")
                
            # Prepare data for charting
            df = trades_df.copy()
            df = df.sort_values('time')
            
            # Calculate cumulative PnL
            if 'closedPnl' in df.columns:
                df['cumulative_pnl'] = df['closedPnl'].cumsum()
            else:
                logger.warning("No closedPnl column found in trades data")
                return self._create_empty_chart("No PnL data available")
                
            # Create the chart
            fig = go.Figure()
            
            # Add cumulative PnL line
            fig.add_trace(go.Scatter(
                x=df['time'],
                y=df['cumulative_pnl'],
                mode='lines+markers',
                name='Cumulative PnL',
                line=dict(color='blue', width=2),
                marker=dict(size=6),
                hovertemplate='<b>%{x}</b><br>' +
                             'Cumulative PnL: $%{y:.2f}<br>' +
                             '<extra></extra>'
            ))
            
            # Add zero line
            fig.add_hline(
                y=0,
                line_dash="dash",
                line_color="gray",
                annotation_text="Break Even"
            )
            
            # Color code based on performance
            final_pnl = df['cumulative_pnl'].iloc[-1] if not df.empty else 0
            title_color = 'green' if final_pnl >= 0 else 'red'
            
            # Update layout
            fig.update_layout(
                title={
                    'text': f'Trading Performance - Total PnL: ${final_pnl:.2f}',
                    'font': {'color': title_color}
                },
                xaxis_title='Time',
                yaxis_title='Cumulative PnL ($)',
                **self.chart_config
            )
            
            return fig
            
        except Exception as e:
            logger.error(f"Error creating PnL chart: {e}")
            return self._create_empty_chart(f"Error: {str(e)}")
            
    def create_trade_distribution_chart(self, trades_df: pd.DataFrame) -> go.Figure:
        """Create trade size/PnL distribution chart."""
        try:
            if trades_df.empty or 'closedPnl' not in trades_df.columns:
                return self._create_empty_chart("No PnL data for distribution")
                
            # Create histogram of PnL
            fig = go.Figure()
            
            pnl_data = trades_df['closedPnl']
            
            # Separate wins and losses
            wins = pnl_data[pnl_data > 0]
            losses = pnl_data[pnl_data < 0]
            
            # Add winning trades histogram
            if not wins.empty:
                fig.add_trace(go.Histogram(
                    x=wins,
                    name='Winning Trades',
                    marker_color='green',
                    opacity=0.7,
                    nbinsx=20
                ))
                
            # Add losing trades histogram
            if not losses.empty:
                fig.add_trace(go.Histogram(
                    x=losses,
                    name='Losing Trades',
                    marker_color='red',
                    opacity=0.7,
                    nbinsx=20
                ))
                
            fig.update_layout(
                title='Trade PnL Distribution',
                xaxis_title='PnL per Trade ($)',
                yaxis_title='Number of Trades',
                barmode='overlay',
                **self.chart_config
            )
            
            return fig
            
        except Exception as e:
            logger.error(f"Error creating distribution chart: {e}")
            return self._create_empty_chart(f"Error: {str(e)}")
            
    def create_volume_chart(self, trades_df: pd.DataFrame) -> go.Figure:
        """Create trading volume chart."""
        try:
            if trades_df.empty:
                return self._create_empty_chart("No trade data for volume chart")
                
            df = trades_df.copy()
            df = df.sort_values('time')
            
            # Calculate hourly volume
            df['hour'] = df['time'].dt.floor('H')
            hourly_volume = df.groupby('hour')['notional'].sum().reset_index()
            
            fig = go.Figure()
            
            fig.add_trace(go.Bar(
                x=hourly_volume['hour'],
                y=hourly_volume['notional'],
                name='Trading Volume',
                marker_color='lightblue',
                hovertemplate='<b>%{x}</b><br>' +
                             'Volume: $%{y:,.0f}<br>' +
                             '<extra></extra>'
            ))
            
            fig.update_layout(
                title='Trading Volume by Hour',
                xaxis_title='Time',
                yaxis_title='Volume ($)',
                **self.chart_config
            )
            
            return fig
            
        except Exception as e:
            logger.error(f"Error creating volume chart: {e}")
            return self._create_empty_chart(f"Error: {str(e)}")
            
    def create_position_chart(self, position_history: List[Dict]) -> go.Figure:
        """Create position size over time chart."""
        try:
            if not position_history:
                return self._create_empty_chart("No position history available")
                
            df = pd.DataFrame(position_history)
            df['time'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('time')
            
            fig = go.Figure()
            
            fig.add_trace(go.Scatter(
                x=df['time'],
                y=df['position_size'],
                mode='lines+markers',
                name='Position Size',
                line=dict(color='orange', width=2),
                marker=dict(size=4),
                hovertemplate='<b>%{x}</b><br>' +
                             'Position: %{y:.4f}<br>' +
                             '<extra></extra>'
            ))
            
            # Add zero line
            fig.add_hline(
                y=0,
                line_dash="dash",
                line_color="gray",
                annotation_text="Flat Position"
            )
            
            fig.update_layout(
                title='Position Size Over Time',
                xaxis_title='Time',
                yaxis_title='Position Size',
                **self.chart_config
            )
            
            return fig
            
        except Exception as e:
            logger.error(f"Error creating position chart: {e}")
            return self._create_empty_chart(f"Error: {str(e)}")
            
    def create_price_chart(self, price_history: List[Dict]) -> go.Figure:
        """Create price movement chart."""
        try:
            if not price_history:
                return self._create_empty_chart("No price history available")
                
            df = pd.DataFrame(price_history)
            df['time'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values('time')
            
            fig = go.Figure()
            
            # Add price line
            fig.add_trace(go.Scatter(
                x=df['time'],
                y=df['price'],
                mode='lines',
                name='Price',
                line=dict(color='black', width=1),
                hovertemplate='<b>%{x}</b><br>' +
                             'Price: $%{y:.2f}<br>' +
                             '<extra></extra>'
            ))
            
            # Add spread area if available
            if 'best_bid' in df.columns and 'best_ask' in df.columns:
                fig.add_trace(go.Scatter(
                    x=df['time'],
                    y=df['best_ask'],
                    mode='lines',
                    name='Ask',
                    line=dict(color='red', width=1, dash='dot'),
                    showlegend=False
                ))
                
                fig.add_trace(go.Scatter(
                    x=df['time'],
                    y=df['best_bid'],
                    mode='lines',
                    name='Bid',
                    line=dict(color='green', width=1, dash='dot'),
                    fill='tonexty',
                    fillcolor='rgba(128,128,128,0.2)',
                    showlegend=False
                ))
                
            fig.update_layout(
                title='Price Movement',
                xaxis_title='Time',
                yaxis_title='Price ($)',
                **self.chart_config
            )
            
            return fig
            
        except Exception as e:
            logger.error(f"Error creating price chart: {e}")
            return self._create_empty_chart(f"Error: {str(e)}")
            
    def create_performance_metrics_chart(self, metrics: Dict[str, float]) -> go.Figure:
        """Create performance metrics summary chart."""
        try:
            if not metrics:
                return self._create_empty_chart("No performance metrics available")
                
            # Create a gauge chart for win rate
            win_rate = metrics.get('win_rate', 0) * 100
            
            fig = go.Figure(go.Indicator(
                mode="gauge+number+delta",
                value=win_rate,
                domain={'x': [0, 1], 'y': [0, 1]},
                title={'text': "Win Rate (%)"},
                delta={'reference': 50},
                gauge={
                    'axis': {'range': [None, 100]},
                    'bar': {'color': "darkblue"},
                    'steps': [
                        {'range': [0, 25], 'color': "red"},
                        {'range': [25, 50], 'color': "orange"},
                        {'range': [50, 75], 'color': "yellow"},
                        {'range': [75, 100], 'color': "green"}
                    ],
                    'threshold': {
                        'line': {'color': "black", 'width': 4},
                        'thickness': 0.75,
                        'value': 50
                    }
                }
            ))
            
            fig.update_layout(
                title='Performance Metrics',
                **self.chart_config
            )
            
            return fig
            
        except Exception as e:
            logger.error(f"Error creating metrics chart: {e}")
            return self._create_empty_chart(f"Error: {str(e)}")
            
    def _create_empty_chart(self, message: str) -> go.Figure:
        """Create an empty chart with a message."""
        fig = go.Figure()
        
        fig.add_annotation(
            x=0.5,
            y=0.5,
            xref='paper',
            yref='paper',
            text=message,
            showarrow=False,
            font=dict(size=16, color="gray")
        )
        
        fig.update_layout(
            title='Chart Unavailable',
            showlegend=False,
            **self.chart_config
        )
        
        return fig
        
    def validate_chart_data(self, data: pd.DataFrame, required_columns: List[str]) -> bool:
        """Validate data before creating charts."""
        try:
            if data.empty:
                return False
                
            missing_columns = [col for col in required_columns if col not in data.columns]
            if missing_columns:
                logger.warning(f"Missing columns for chart: {missing_columns}")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error validating chart data: {e}")
            return False