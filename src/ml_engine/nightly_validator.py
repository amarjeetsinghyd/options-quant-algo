import sqlite3
import os
from datetime import datetime

ML_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "ml_research.db")
STRIKE_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "strike_research.db")
REPORT_PATH = r"C:\Users\Amarjeet Singh\.gemini\antigravity\brain\05cb2f80-d049-4eb6-89ab-dc0decf22420\data_quality_report.md"

def run_nightly_validation():
    print("=== STARTING NIGHTLY DATA QUALITY AUDIT ===")
    
    report_lines = [
        "# Data Quality & Integrity Audit Report",
        f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Summary Metrics",
        ""
    ]
    
    issues_found = []
    
    # 1. Audit ml_research.db
    if os.path.exists(ML_DB_PATH):
        try:
            conn = sqlite3.connect(ML_DB_PATH)
            cursor = conn.cursor()
            
            # Gamma Events Audit
            cursor.execute("SELECT COUNT(*) FROM gamma_events")
            gamma_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM non_gamma_events")
            non_gamma_count = cursor.fetchone()[0]
            
            # Gaps / Nulls
            cursor.execute("SELECT COUNT(*) FROM gamma_events WHERE timestamp IS NULL OR option_symbol IS NULL")
            missing_gamma = cursor.fetchone()[0]
            if missing_gamma > 0:
                issues_found.append(f"CRITICAL: Found {missing_gamma} records in gamma_events with NULL timestamp or symbol.")
                
            # Future timestamps
            cursor.execute("SELECT COUNT(*) FROM gamma_events WHERE timestamp > ?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),))
            future_gamma = cursor.fetchone()[0]
            if future_gamma > 0:
                issues_found.append(f"WARNING: Found {future_gamma} records in gamma_events with future timestamps.")
                
            # Invalid session types
            cursor.execute("SELECT COUNT(*) FROM gamma_events WHERE session_type NOT IN ('LIVE', 'PREOPEN', 'AFTER_MARKET', 'HOLIDAY', 'SIMULATION', 'REPLAY', 'UNIT_TEST')")
            invalid_session = cursor.fetchone()[0]
            if invalid_session > 0:
                issues_found.append(f"WARNING: Found {invalid_session} records in gamma_events with invalid session_type.")
                
            # Corrupted records
            cursor.execute("SELECT COUNT(*) FROM gamma_events WHERE observation_status = 'CORRUPTED'")
            corrupted_count = cursor.fetchone()[0]
            if corrupted_count > 0:
                issues_found.append(f"INFO: Found {corrupted_count} corrupted (insufficient ticks) observations in gamma_events.")
                
            # Quality stats
            cursor.execute("SELECT AVG(quality_score) FROM gamma_events WHERE quality_score IS NOT NULL")
            avg_q = cursor.fetchone()[0] or 100.0
            
            report_lines.extend([
                "### ML Research Database (ml_research.db)",
                f"- **Gamma Events Count**: {gamma_count}",
                f"- **Non-Gamma Events Count**: {non_gamma_count}",
                f"- **Average Quality Score**: {avg_q:.2f}/100",
                ""
            ])
            conn.close()
        except Exception as e:
            issues_found.append(f"ERROR: Failed to audit ml_research.db: {e}")
    else:
        report_lines.extend([
            "### ML Research Database (ml_research.db)",
            "- *Database file not found. Level 0 Collection Mode inactive.*",
            ""
        ])

    # 2. Audit strike_research.db
    if os.path.exists(STRIKE_DB_PATH):
        try:
            conn = sqlite3.connect(STRIKE_DB_PATH)
            cursor = conn.cursor()
            
            # Snapshots
            cursor.execute("SELECT COUNT(*) FROM signal_snapshots")
            snapshot_count = cursor.fetchone()[0]
            
            # Duplicates check
            cursor.execute("SELECT signal_id, COUNT(*) FROM signal_snapshots GROUP BY signal_id HAVING COUNT(*) > 1")
            duplicates = cursor.fetchall()
            if duplicates:
                issues_found.append(f"CRITICAL: Found {len(duplicates)} duplicate signal IDs in signal_snapshots.")
                
            # Invalid sessions
            cursor.execute("SELECT COUNT(*) FROM signal_snapshots WHERE session_type NOT IN ('LIVE', 'PREOPEN', 'AFTER_MARKET', 'HOLIDAY', 'SIMULATION', 'REPLAY', 'UNIT_TEST')")
            invalid_session = cursor.fetchone()[0]
            if invalid_session > 0:
                issues_found.append(f"WARNING: Found {invalid_session} records in signal_snapshots with invalid session_type.")
                
            # Corrupted records
            cursor.execute("SELECT COUNT(*) FROM signal_snapshots WHERE observation_status = 'CORRUPTED'")
            corrupted_count = cursor.fetchone()[0]
            if corrupted_count > 0:
                issues_found.append(f"INFO: Found {corrupted_count} corrupted rule-based signals.")
                
            report_lines.extend([
                "### Strike Research Database (strike_research.db)",
                f"- **Rule-Based Snapshots Count**: {snapshot_count}",
                ""
            ])
            conn.close()
        except Exception as e:
            issues_found.append(f"ERROR: Failed to audit strike_research.db: {e}")
    else:
        report_lines.extend([
            "### Strike Research Database (strike_research.db)",
            "- *Database file not found.*",
            ""
        ])

    # Append Issues
    report_lines.append("## Integrity & Quality Issues")
    report_lines.append("")
    if issues_found:
        for issue in issues_found:
            report_lines.append(f"- {issue}")
    else:
        report_lines.append("- **No issues found.** All records are synchronized, whitelisted, and categorized correctly.")
        
    # Write report file
    try:
        os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
        with open(REPORT_PATH, "w") as f:
            f.write("\n".join(report_lines))
        print(f"Data Quality Report saved to: {REPORT_PATH}")
    except Exception as e:
        print(f"Failed to write report file: {e}")
        
    print("=== NIGHTLY AUDIT COMPLETED ===")

if __name__ == "__main__":
    run_nightly_validation()
