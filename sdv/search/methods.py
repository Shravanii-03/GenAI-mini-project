"""
Search methods over the unit cube [0,1]^d. All share an ask/tell interface and
minimise f (negative f = success).

  RandomSearch        uniform sampling
  GridSearch          coarse grid, visited in random order
  BanditQLearning     tabular Q-learning with a single state, as in the original RL
                      component (epsilon-greedy, alpha=0.15); arms are grid cells
  EvolutionStrategy   (1+1)-ES with the 1/5-success-style step adaptation
  BayesOpt            Gaussian-process surrogate + expected improvement
                      (optionally warm-started with given initial points, which is
                      how the LLM prior enters)
"""
import math

import numpy as np

_erf = np.vectorize(math.erf)


class Method:
    name = "method"

    def __init__(self, dim: int, rng: np.random.Generator, budget: int = 60):
        self.dim, self.rng, self.budget = dim, rng, budget

    def ask(self):
        raise NotImplementedError

    def tell(self, u, f):
        pass


class RandomSearch(Method):
    name = "random"

    def ask(self):
        return self.rng.random(self.dim)


class GridSearch(Method):
    name = "grid"

    def __init__(self, dim, rng, budget=60):
        super().__init__(dim, rng, budget)
        m = max(2, round(budget ** (1.0 / dim)))
        axes = [(np.arange(m) + 0.5) / m] * dim
        points = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, dim)
        self._points = list(points[rng.permutation(len(points))])

    def ask(self):
        return self._points.pop(0) if self._points else self.rng.random(self.dim)


class BanditQLearning(Method):
    name = "q_learning"

    def __init__(self, dim, rng, budget=60, cells=3, alpha=0.15, eps0=0.5, eps_decay=0.97, eps_min=0.05):
        super().__init__(dim, rng, budget)
        self.cells, self.alpha = cells, alpha
        self.eps0, self.eps_decay, self.eps_min = eps0, eps_decay, eps_min
        self.q = np.zeros(cells ** dim)
        self.t, self._arm = 0, 0

    def ask(self):
        eps = max(self.eps_min, self.eps0 * self.eps_decay ** self.t)
        if self.rng.random() < eps:
            arm = int(self.rng.integers(len(self.q)))
        else:
            arm = int(np.argmax(self.q + 1e-9 * self.rng.random(len(self.q))))
        self._arm = arm
        index, cell = [], arm
        for _ in range(self.dim):
            index.append(cell % self.cells)
            cell //= self.cells
        return (np.array(index) + self.rng.random(self.dim)) / self.cells

    def tell(self, u, f):
        reward = -max(-1.0, min(1.0, f / 1000.0))
        self.q[self._arm] += self.alpha * (reward - self.q[self._arm])
        self.t += 1


class EvolutionStrategy(Method):
    name = "es"

    def __init__(self, dim, rng, budget=60, sigma=0.25):
        super().__init__(dim, rng, budget)
        self.sigma, self.parent, self.f_parent, self._child = sigma, None, None, None

    def ask(self):
        if self.parent is None:
            self._child = self.rng.random(self.dim)
        else:
            self._child = np.clip(self.parent + self.sigma * self.rng.standard_normal(self.dim), 0, 1)
        return self._child

    def tell(self, u, f):
        if self.parent is None or f <= self.f_parent:
            improved = self.parent is not None
            self.parent, self.f_parent = u, f
            if improved:
                self.sigma = min(0.5, self.sigma * 1.4)
        else:
            self.sigma = max(0.02, self.sigma * 1.4 ** -0.25)


class BayesOpt(Method):
    name = "bayes_opt"

    def __init__(self, dim, rng, budget=60, n_init=8, init_points=None,
                 n_candidates=512, lengthscale=0.3, noise=0.05):
        super().__init__(dim, rng, budget)
        self._init = [np.asarray(p, dtype=float) for p in init_points] if init_points is not None else []
        if init_points is None:
            self._init = [rng.random(dim) for _ in range(n_init)]
        self.n_candidates, self.lengthscale, self.noise = n_candidates, lengthscale, noise
        self.X, self.y = [], []

    def _kernel(self, A, B):
        d2 = ((A[:, None, :] - B[None, :, :]) ** 2).sum(-1)
        return np.exp(-0.5 * d2 / self.lengthscale ** 2)

    def ask(self):
        if self._init:
            return self._init.pop(0)
        if len(self.X) < 3:
            return self.rng.random(self.dim)
        X, y = np.array(self.X), np.array(self.y)
        scale = y.std() or 1.0
        ys = (y - y.mean()) / scale
        K = self._kernel(X, X) + self.noise * np.eye(len(X))
        L = np.linalg.cholesky(K)
        alpha = np.linalg.solve(L.T, np.linalg.solve(L, ys))
        best_points = X[np.argsort(ys)[:3]]
        local = np.clip(best_points[self.rng.integers(len(best_points), size=self.n_candidates // 2)]
                        + 0.08 * self.rng.standard_normal((self.n_candidates // 2, self.dim)), 0, 1)
        cand = np.vstack([self.rng.random((self.n_candidates // 2, self.dim)), local])
        Ks = self._kernel(cand, X)
        mu = Ks @ alpha
        v = np.linalg.solve(L, Ks.T)
        sd = np.sqrt(np.maximum(1.0 - (v ** 2).sum(0), 1e-12))
        z = (ys.min() - mu) / sd
        cdf = 0.5 * (1 + _erf(z / math.sqrt(2)))
        pdf = np.exp(-0.5 * z ** 2) / math.sqrt(2 * math.pi)
        ei = (ys.min() - mu) * cdf + sd * pdf
        return cand[int(np.argmax(ei))]

    def tell(self, u, f):
        self.X.append(np.asarray(u, dtype=float))
        self.y.append(float(f))


METHODS = {cls.name: cls for cls in (RandomSearch, GridSearch, BanditQLearning, EvolutionStrategy, BayesOpt)}


def run_search(problem, method: Method, budget: int, base_seed: int = 0, stop_on_success: bool = True):
    """Run a method on a problem. The i-th evaluation always uses seed base_seed+i, so
    methods are compared on identical noise realisations."""
    history = []
    for i in range(budget):
        u = np.clip(np.asarray(method.ask(), dtype=float), 0.0, 1.0)
        out = problem.evaluate(u, base_seed + i)
        method.tell(u, out["f"])
        history.append({"i": i + 1, "f": out["f"], "success": out["success"], "u": u})
        if stop_on_success and out["success"]:
            break
    first = next((h["i"] for h in history if h["success"]), None)
    return {"history": history, "first_success": first,
            "best_f": min(h["f"] for h in history), "evaluations": len(history)}
