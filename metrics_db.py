import sqlite3
import json
from datetime import datetime, timedelta
import pandas as pd

class MetricsDatabase:
    """SQLite database for storing 24h metric history"""

    def __init__(self, db_path="metrics_history.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """Initialize database schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                cluster_name TEXT,
                kv_cache_usage REAL,
                num_requests_running INTEGER,
                num_requests_waiting INTEGER,
                failure_rate REAL,
                latency_p90 REAL,
                tokens_per_second INTEGER,
                prompt_tokens_total INTEGER,
                generation_tokens_total INTEGER,
                metrics_json TEXT
            )
        """)

        # Create AI feedback table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                cluster_name TEXT,
                user_question TEXT,
                ai_response TEXT,
                rating TEXT CHECK(rating IN ('thumbs_up', 'thumbs_down')),
                metrics_snapshot TEXT,
                session_id TEXT,
                response_time_ms INTEGER
            )
        """)

        # Create AI insights table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                cluster_name TEXT,
                severity TEXT,
                insight_text TEXT,
                metrics_snapshot TEXT
            )
        """)

        # Create chat history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                cluster_name TEXT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                metrics_snapshot TEXT
            )
        """)

        # Create index for faster queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_timestamp
            ON metrics(timestamp)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_feedback_timestamp
            ON ai_feedback(timestamp)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_feedback_rating
            ON ai_feedback(rating)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_insights_timestamp
            ON ai_insights(timestamp)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_timestamp
            ON chat_history(timestamp)
        """)

        conn.commit()
        conn.close()

    def save_metrics(self, cluster_name, metrics):
        """Save current metrics snapshot"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO metrics (
                cluster_name,
                kv_cache_usage,
                num_requests_running,
                num_requests_waiting,
                failure_rate,
                latency_p90,
                tokens_per_second,
                prompt_tokens_total,
                generation_tokens_total,
                metrics_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cluster_name,
            metrics.get('gpu_utilization', 0),
            metrics.get('num_requests_running', 0),
            metrics.get('num_requests_waiting', 0),
            metrics.get('request_failure_rate', 0),
            metrics.get('e2e_request_latency_p90', 0),
            metrics.get('tokens_per_second', 0),
            metrics.get('prompt_tokens_total', 0),
            metrics.get('generation_tokens_total', 0),
            json.dumps(metrics)
        ))

        conn.commit()
        conn.close()

    def cleanup_old_data(self):
        """Delete data older than 24 hours"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cutoff = datetime.now() - timedelta(hours=24)
        cursor.execute("""
            DELETE FROM metrics
            WHERE timestamp < ?
        """, (cutoff,))

        conn.commit()
        conn.close()

    def get_recent_metrics(self, hours=1, cluster_name=None):
        """Get metrics from last N hours"""
        conn = sqlite3.connect(self.db_path)

        cutoff = datetime.now() - timedelta(hours=hours)

        if cluster_name:
            query = """
                SELECT * FROM metrics
                WHERE timestamp >= ? AND cluster_name = ?
                ORDER BY timestamp DESC
            """
            df = pd.read_sql_query(query, conn, params=(cutoff, cluster_name))
        else:
            query = """
                SELECT * FROM metrics
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
            """
            df = pd.read_sql_query(query, conn, params=(cutoff,))

        conn.close()
        return df

    def get_metric_at_time(self, minutes_ago, cluster_name=None):
        """Get metrics from N minutes ago"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        target_time = datetime.now() - timedelta(minutes=minutes_ago)

        if cluster_name:
            cursor.execute("""
                SELECT * FROM metrics
                WHERE cluster_name = ?
                ORDER BY ABS(strftime('%s', timestamp) - strftime('%s', ?))
                LIMIT 1
            """, (cluster_name, target_time))
        else:
            cursor.execute("""
                SELECT * FROM metrics
                ORDER BY ABS(strftime('%s', timestamp) - strftime('%s', ?))
                LIMIT 1
            """, (target_time,))

        result = cursor.fetchone()
        conn.close()
        return result

    def export_to_csv(self, hours=24, cluster_name=None):
        """Export metrics to CSV"""
        df = self.get_recent_metrics(hours=hours, cluster_name=cluster_name)

        if df.empty:
            return None

        # Select relevant columns
        export_df = df[[
            'timestamp', 'cluster_name', 'kv_cache_usage',
            'num_requests_running', 'num_requests_waiting',
            'failure_rate', 'latency_p90', 'tokens_per_second',
            'prompt_tokens_total', 'generation_tokens_total'
        ]]

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"metrics_export_{timestamp}.csv"
        export_df.to_csv(filename, index=False)

        return filename

    def get_summary_stats(self, hours=1, cluster_name=None):
        """Get summary statistics for time period"""
        df = self.get_recent_metrics(hours=hours, cluster_name=cluster_name)

        if df.empty:
            return None

        summary = {
            'avg_kv_cache': df['kv_cache_usage'].mean(),
            'max_kv_cache': df['kv_cache_usage'].max(),
            'avg_latency': df['latency_p90'].mean(),
            'max_latency': df['latency_p90'].max(),
            'avg_running_requests': df['num_requests_running'].mean(),
            'max_queue': df['num_requests_waiting'].max(),
            'total_tokens_generated': df['generation_tokens_total'].max() - df['generation_tokens_total'].min(),
            'data_points': len(df)
        }

        return summary

    def save_feedback(self, cluster_name, user_question, ai_response, rating,
                     metrics_snapshot, session_id, response_time_ms=None):
        """
        Save user feedback on AI response.

        Args:
            cluster_name: Name of cluster being monitored
            user_question: User's original question
            ai_response: AI's recommendation/response
            rating: 'thumbs_up' or 'thumbs_down'
            metrics_snapshot: Current metrics at time of question
            session_id: Streamlit session ID for tracking
            response_time_ms: Time taken to generate response in milliseconds
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO ai_feedback (
                cluster_name,
                user_question,
                ai_response,
                rating,
                metrics_snapshot,
                session_id,
                response_time_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            cluster_name,
            user_question,
            ai_response,
            rating,
            json.dumps(metrics_snapshot),
            session_id,
            response_time_ms
        ))

        conn.commit()
        conn.close()

    def get_feedback_stats(self, hours=24, cluster_name=None):
        """
        Get feedback statistics.

        Args:
            hours: Number of hours to look back
            cluster_name: Optional cluster name filter

        Returns:
            Dict with stats or None if no feedback:
            {
                'total_feedback': int,
                'thumbs_up': int,
                'thumbs_down': int,
                'satisfaction_rate': float,
                'avg_response_time_ms': float
            }
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cutoff = datetime.now() - timedelta(hours=hours)

        if cluster_name:
            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN rating = 'thumbs_up' THEN 1 ELSE 0 END) as thumbs_up,
                    SUM(CASE WHEN rating = 'thumbs_down' THEN 1 ELSE 0 END) as thumbs_down,
                    AVG(response_time_ms) as avg_response_time
                FROM ai_feedback
                WHERE timestamp >= ? AND cluster_name = ?
            """, (cutoff, cluster_name))
        else:
            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN rating = 'thumbs_up' THEN 1 ELSE 0 END) as thumbs_up,
                    SUM(CASE WHEN rating = 'thumbs_down' THEN 1 ELSE 0 END) as thumbs_down,
                    AVG(response_time_ms) as avg_response_time
                FROM ai_feedback
                WHERE timestamp >= ?
            """, (cutoff,))

        result = cursor.fetchone()
        conn.close()

        if result and result[0] > 0:
            total, thumbs_up, thumbs_down, avg_response_time = result
            return {
                'total_feedback': total,
                'thumbs_up': thumbs_up,
                'thumbs_down': thumbs_down,
                'satisfaction_rate': (thumbs_up / total * 100) if total > 0 else 0,
                'avg_response_time_ms': avg_response_time or 0
            }
        return None

    def get_recent_feedback(self, hours=24, cluster_name=None, limit=10):
        """
        Get recent feedback entries for review.

        Args:
            hours: Number of hours to look back
            cluster_name: Optional cluster name filter
            limit: Maximum number of entries to return

        Returns:
            pandas DataFrame with recent feedback
        """
        conn = sqlite3.connect(self.db_path)

        cutoff = datetime.now() - timedelta(hours=hours)

        if cluster_name:
            query = """
                SELECT timestamp, user_question, ai_response, rating, response_time_ms
                FROM ai_feedback
                WHERE timestamp >= ? AND cluster_name = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """
            df = pd.read_sql_query(query, conn, params=(cutoff, cluster_name, limit))
        else:
            query = """
                SELECT timestamp, cluster_name, user_question, ai_response, rating, response_time_ms
                FROM ai_feedback
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT ?
            """
            df = pd.read_sql_query(query, conn, params=(cutoff, limit))

        conn.close()
        return df

    def export_feedback_to_csv(self, hours=24, cluster_name=None):
        """
        Export feedback data for training/analysis.

        Args:
            hours: Number of hours to look back
            cluster_name: Optional cluster name filter

        Returns:
            Filename of exported CSV or None if no data
        """
        df = self.get_recent_feedback(hours=hours, cluster_name=cluster_name, limit=10000)

        if df.empty:
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"ai_feedback_export_{timestamp}.csv"
        df.to_csv(filename, index=False)

        return filename

    def save_ai_insight(self, cluster_name, severity, insight_text, metrics_snapshot):
        """
        Save AI-generated insight to database.

        Args:
            cluster_name: Name of cluster
            severity: CRITICAL, WARNING, or INFO
            insight_text: The AI's insight/recommendation
            metrics_snapshot: Metrics at time of insight generation
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO ai_insights (
                cluster_name,
                severity,
                insight_text,
                metrics_snapshot
            ) VALUES (?, ?, ?, ?)
        """, (
            cluster_name,
            severity,
            insight_text,
            json.dumps(metrics_snapshot)
        ))

        conn.commit()
        conn.close()

    def get_recent_insights(self, hours=24, cluster_name=None, limit=50):
        """
        Get recent AI insights.

        Args:
            hours: Number of hours to look back
            cluster_name: Optional cluster name filter
            limit: Maximum number of entries

        Returns:
            pandas DataFrame with recent insights
        """
        conn = sqlite3.connect(self.db_path)

        cutoff = datetime.now() - timedelta(hours=hours)

        if cluster_name:
            query = """
                SELECT timestamp, severity, insight_text
                FROM ai_insights
                WHERE timestamp >= ? AND cluster_name = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """
            df = pd.read_sql_query(query, conn, params=(cutoff, cluster_name, limit))
        else:
            query = """
                SELECT timestamp, cluster_name, severity, insight_text
                FROM ai_insights
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT ?
            """
            df = pd.read_sql_query(query, conn, params=(cutoff, limit))

        conn.close()
        return df

    def save_chat_message(self, cluster_name, session_id, role, content, metrics_snapshot):
        """
        Save chat message to database.

        Args:
            cluster_name: Name of cluster
            session_id: Session identifier
            role: 'user' or 'assistant'
            content: Message content
            metrics_snapshot: Metrics at time of message
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO chat_history (
                cluster_name,
                session_id,
                role,
                content,
                metrics_snapshot
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            cluster_name,
            session_id,
            role,
            content,
            json.dumps(metrics_snapshot)
        ))

        conn.commit()
        conn.close()

    def get_recent_chat_history(self, hours=24, cluster_name=None, limit=100):
        """
        Get recent chat messages.

        Args:
            hours: Number of hours to look back
            cluster_name: Optional cluster name filter
            limit: Maximum number of messages

        Returns:
            pandas DataFrame with chat history
        """
        conn = sqlite3.connect(self.db_path)

        cutoff = datetime.now() - timedelta(hours=hours)

        if cluster_name:
            query = """
                SELECT timestamp, session_id, role, content
                FROM chat_history
                WHERE timestamp >= ? AND cluster_name = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """
            df = pd.read_sql_query(query, conn, params=(cutoff, cluster_name, limit))
        else:
            query = """
                SELECT timestamp, cluster_name, session_id, role, content
                FROM chat_history
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT ?
            """
            df = pd.read_sql_query(query, conn, params=(cutoff, limit))

        conn.close()
        return df

    def load_chat_history_for_session(self, cluster_name, session_id, hours=24):
        """
        Load chat history for current session to restore on page refresh.

        Args:
            cluster_name: Name of cluster
            session_id: Session identifier
            hours: How far back to look

        Returns:
            List of message dicts [{"role": "user", "content": "..."}]
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cutoff = datetime.now() - timedelta(hours=hours)

        cursor.execute("""
            SELECT role, content
            FROM chat_history
            WHERE cluster_name = ? AND session_id = ? AND timestamp >= ?
            ORDER BY timestamp ASC
        """, (cluster_name, session_id, cutoff))

        messages = []
        for row in cursor.fetchall():
            messages.append({"role": row[0], "content": row[1]})

        conn.close()
        return messages
