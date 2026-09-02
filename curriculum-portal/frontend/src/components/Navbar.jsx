import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';
import './Navbar.css';

export default function Navbar() {
  const { isAuthenticated, user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const linkClass = ({ isActive }) => `navbar__link${isActive ? ' navbar__link--active' : ''}`;

  return (
    <header className="navbar">
      <NavLink to="/" className="navbar__brand">
        <span className="navbar__mark" aria-hidden="true" />
        Curriculum Portal
      </NavLink>

      <nav className="navbar__links">
        {isAuthenticated ? (
          <>
            <NavLink to="/" end className={linkClass}>
              Upload
            </NavLink>
            <NavLink to="/dashboard" className={linkClass}>
              Dashboard
            </NavLink>
            <NavLink to="/compare" className={linkClass}>
              Compare
            </NavLink>
            <div className="navbar__user">
              <span className="navbar__email">{user?.email}</span>
              <button type="button" className="btn btn--ghost btn--sm" onClick={handleLogout}>
                Log out
              </button>
            </div>
          </>
        ) : (
          <>
            <NavLink to="/login" className={linkClass}>
              Log in
            </NavLink>
            <NavLink to="/signup" className="btn btn--primary btn--sm">
              Sign up
            </NavLink>
          </>
        )}
      </nav>
    </header>
  );
}
