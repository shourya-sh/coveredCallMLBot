import { Loader2 } from 'lucide-react';
import './LoadingSpinner.css';

export default function LoadingSpinner({ message = 'Loading...' }) {
  return (
    <div className="spinner-container">
      <Loader2 size={32} className="spin" />
      <span>{message}</span>
    </div>
  );
}
