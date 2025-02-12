from __future__ import absolute_import, print_function, unicode_literals
from builtins import dict, str
import os
import sys
import time
try:
    # Python 2
    import cPickle as pickle
except ImportError:
    # Python 3
    import pickle
import logging
from copy import deepcopy
from indra.statements import *
from indra.belief import BeliefEngine
from indra.databases import uniprot_client
from indra.mechlinker import MechLinker
from indra.preassembler import Preassembler
from indra.tools.expand_families import Expander
from indra.preassembler.hierarchy_manager import hierarchies
from indra.preassembler.grounding_mapper import GroundingMapper
from indra.preassembler.grounding_mapper import gm as grounding_map
from indra.preassembler.sitemapper import SiteMapper, default_site_map

logger = logging.getLogger('assemble_corpus')
indra_logger = logging.getLogger('indra').setLevel(logging.DEBUG)

def dump_statements(stmts, fname):
    """Dump a list of statements into a pickle file.

    Parameters
    ----------
    fname : str
        The name of the pickle file to dump statements into.
    """
    logger.info('Dumping %d statements into %s...' % (len(stmts), fname))
    with open(fname, 'wb') as fh:
        pickle.dump(stmts, fh, protocol=2)

def load_statements(fname, as_dict=False):
    """Load statements from a pickle file.

    Parameters
    ----------
    fname : str
        The name of the pickle file to load statements from.
    as_dict : Optional[bool]
        If True and the pickle file contains a dictionary of statements, it
        is returned as a dictionary. If False, the statements are always
        returned in a list. Default: False

    Returns
    -------
    stmts : list
        A list or dict of statements that were loaded.
    """
    logger.info('Loading %s...' % fname)
    with open(fname, 'rb') as fh:
        stmts = pickle.load(fh)
    if isinstance(stmts, dict):
        if as_dict:
            return stmts
        st = []
        for pmid, st_list in stmts.items():
            st += st_list
        stmts = st
    logger.info('Loaded %d statements' % len(stmts))
    return stmts

def map_grounding(stmts_in, **kwargs):
    """Map grounding using the GroundingMapper.

    Parameters
    ----------
    stmts_in : list[indra.statements.Statement]
        A list of statements to map.
    do_rename : Optional[bool]
        If True, Agents are renamed based on their mapped grounding.
    save : Optional[str]
        The name of a pickle file to save the results (stmts_out) into.

    Returns
    -------
    stmts_out : list[indra.statements.Statement]
        A list of mapped statements.
    """
    logger.info('Mapping grounding on %d statements...' % len(stmts_in))
    do_rename = kwargs.get('do_rename')
    if do_rename is None:
        do_rename = True
    gm = GroundingMapper(grounding_map)
    stmts_out = gm.map_agents(stmts_in, do_rename=do_rename)
    dump_pkl = kwargs.get('save')
    if dump_pkl:
        dump_statements(stmts_out, dump_pkl)
    return stmts_out

def map_sequence(stmts_in, **kwargs):
    """Map sequences using the SiteMapper.

    Parameters
    ----------
    stmts_in : list[indra.statements.Statement]
        A list of statements to map.
    save : Optional[str]
        The name of a pickle file to save the results (stmts_out) into.

    Returns
    -------
    stmts_out : list[indra.statements.Statement]
        A list of mapped statements.
    """
    logger.info('Mapping sites on %d statements...' % len(stmts_in))
    sm = SiteMapper(default_site_map)
    valid, mapped = sm.map_sites(stmts_in)
    correctly_mapped_stmts = []
    for ms in mapped:
        if all([True if mm[1] is not None else False
                for mm in ms.mapped_mods]):
            correctly_mapped_stmts.append(ms.mapped_stmt)
    stmts_out = valid + correctly_mapped_stmts
    logger.info('%d statements with valid sites' % len(stmts_out))
    dump_pkl = kwargs.get('save')
    if dump_pkl:
        dump_statements(stmts_out, dump_pkl)
    return stmts_out

def run_preassembly(stmts_in, **kwargs):
    """Run preassembly on a list of statements.

    Parameters
    ----------
    stmts_in : list[indra.statements.Statement]
        A list of statements to preassemble.
    return_toplevel : Optional[bool]
        If True, only the top-level statements are returned. If False,
        all statements are returned irrespective of level of specificity.
        Default: True
    save : Optional[str]
        The name of a pickle file to save the results (stmts_out) into.
    save_unique : Optional[str]
        The name of a pickle file to save the unique statements into.

    Returns
    -------
    stmts_out : list[indra.statements.Statement]
        A list of preassembled top-level statements.
    """
    dump_pkl = kwargs.get('save')
    dump_pkl_unique = kwargs.get('save_unique')
    be = BeliefEngine()
    pa = Preassembler(hierarchies, stmts_in)

    options = {'save': dump_pkl_unique}
    run_preassembly_duplicate(pa, be, **options)

    return_toplevel = kwargs.get('return_toplevel', True)
    options = {'save': dump_pkl, 'return_toplevel': return_toplevel}
    start = time.time()
    stmts_out = run_preassembly_related(pa, be, **options)
    end = time.time()
    elapsed = end - start
    logger.debug("Time elapsed, run_preassembly_related: %s" % elapsed)
    return stmts_out

def run_preassembly_duplicate(preassembler, beliefengine, **kwargs):
    """Run deduplication stage of preassembly on a list of statements.

    Parameters
    ----------
    preassembler : indra.preassembler.Preassembler
        A Preassembler instance
    beliefengine : indra.belief.BeliefEngine
        A BeliefEngine instance
    save : Optional[str]
        The name of a pickle file to save the results (stmts_out) into.

    Returns
    -------
    stmts_out : list[indra.statements.Statement]
        A list of unique statements.
    """
    logger.info('Combining duplicates on %d statements...' %
                len(preassembler.stmts))
    dump_pkl = kwargs.get('save')
    stmts_out = preassembler.combine_duplicates()
    beliefengine.set_prior_probs(stmts_out)
    logger.info('%d unique statements' % len(stmts_out))
    if dump_pkl:
        dump_statements(stmts_out, dump_pkl)
    return stmts_out

def run_preassembly_related(preassembler, beliefengine, **kwargs):
    """Run related stage of preassembly on a list of statements.

    Parameters
    ----------
    preassembler : indra.preassembler.Preassembler
        A Preassembler instance which already has a set of unique statements
        internally.
    beliefengine : indra.belief.BeliefEngine
        A BeliefEngine instance
    return_toplevel : Optional[bool]
        If True, only the top-level statements are returned. If False,
        all statements are returned irrespective of level of specificity.
        Default: True
    save : Optional[str]
        The name of a pickle file to save the results (stmts_out) into.

    Returns
    -------
    stmts_out : list[indra.statements.Statement]
        A list of preassembled top-level statements.
    """
    logger.info('Combining related on %d statements...' %
                len(preassembler.unique_stmts))
    return_toplevel = kwargs.get('return_toplevel', True)
    stmts_out = preassembler.combine_related(return_toplevel=False)
    beliefengine.set_hierarchy_probs(stmts_out)
    stmts_top = filter_top_level(stmts_out)
    if return_toplevel:
        stmts_out = stmts_top
        logger.info('%d top-level statements' % len(stmts_out))
    else:
        logger.info('%d statements out of which %d are top-level' %
                    (len(stmts_out), len(stmts_top)))

    dump_pkl = kwargs.get('save')
    if dump_pkl:
        dump_statements(stmts_out, dump_pkl)
    return stmts_out

def filter_by_type(stmts_in, stmt_type, **kwargs):
    """Filter to a given statement type.

    Parameters
    ----------
    stmts_in : list[indra.statements.Statement]
        A list of statements to filter.
    stmt_type : indra.statements.Statement
        The class of the statement type to filter for.
        Example: indra.statements.Modification
    save : Optional[str]
        The name of a pickle file to save the results (stmts_out) into.

    Returns
    -------
    stmts_out : list[indra.statements.Statement]
        A list of filtered statements.
    """
    logger.info('Filtering %d statements...' % len(stmts_in))
    stmts_out = [st for st in stmts_in if isinstance(st, stmt_type)]
    logger.info('%d statements after filter...' % len(stmts_out))
    dump_pkl = kwargs.get('save')
    if dump_pkl:
        dump_statements(stmts_out, dump_pkl)
    return stmts_out

def filter_grounded_only(stmts_in, **kwargs):
    """Filter to statements that have grounded agents.

    Parameters
    ----------
    stmts_in : list[indra.statements.Statement]
        A list of statements to filter.
    save : Optional[str]
        The name of a pickle file to save the results (stmts_out) into.

    Returns
    -------
    stmts_out : list[indra.statements.Statement]
        A list of filtered statements.
    """
    logger.info('Filtering %d statements for grounded agents...' % 
                len(stmts_in))
    stmts_out = []
    for st in stmts_in:
        grounded = True
        for agent in st.agent_list():
            if agent is not None:
                if (not agent.db_refs) or \
                   ((len(agent.db_refs) == 1) and agent.db_refs.get('TEXT')):
                    grounded = False
                    break
        if grounded:
            stmts_out.append(st)
    logger.info('%d statements after filter...' % len(stmts_out))
    dump_pkl = kwargs.get('save')
    if dump_pkl:
        dump_statements(stmts_out, dump_pkl)
    return stmts_out

def filter_genes_only(stmts_in, **kwargs):
    """Filter to statements containing genes only.

    Parameters
    ----------
    stmts_in : list[indra.statements.Statement]
        A list of statements to filter.
    specific_only : Optional[bool]
        If True, only elementary genes/proteins will be kept and families
        will be filtered out. If False, families are also included in the
        output. Default: False
    save : Optional[str]
        The name of a pickle file to save the results (stmts_out) into.

    Returns
    -------
    stmts_out : list[indra.statements.Statement]
        A list of filtered statements.
    """
    specific_only = kwargs.get('specific_only')
    logger.info('Filtering %d statements for ones containing genes only...' % 
                len(stmts_in))
    stmts_out = []
    for st in stmts_in:
        genes_only = True
        for agent in st.agent_list():
            if agent is not None:
                if not specific_only:
                    if not(agent.db_refs.get('HGNC') or \
                           agent.db_refs.get('UP') or \
                           agent.db_refs.get('BE')):
                        genes_only = False
                        break
                else:
                    if not(agent.db_refs.get('HGNC') or \
                           agent.db_refs.get('UP')):
                        genes_only = False
                        break
        if genes_only:
            stmts_out.append(st)
    logger.info('%d statements after filter...' % len(stmts_out))
    dump_pkl = kwargs.get('save')
    if dump_pkl:
        dump_statements(stmts_out, dump_pkl)
    return stmts_out

def filter_belief(stmts_in, belief_cutoff, **kwargs):
    """Filter to statements with belief above a given cutoff.

    Parameters
    ----------
    stmts_in : list[indra.statements.Statement]
        A list of statements to filter.
    belief_cutoff : float
        Only statements with belief above the belief_cutoff will be returned.
        Here 0 < belief_cutoff < 1.
    save : Optional[str]
        The name of a pickle file to save the results (stmts_out) into.

    Returns
    -------
    stmts_out : list[indra.statements.Statement]
        A list of filtered statements.
    """
    dump_pkl = kwargs.get('save')
    logger.info('Filtering %d statements to above %f belief' %
                (len(stmts_in), belief_cutoff))
    stmts_out = [s for s in stmts_in if s.belief >= belief_cutoff]
    logger.info('%d statements after filter...' % len(stmts_out))
    if dump_pkl:
        dump_statements(stmts_out, dump_pkl)
    return stmts_out

def filter_gene_list(stmts_in, gene_list, policy, **kwargs):
    """Return statements that contain genes given in a list.

    Parameters
    ----------
    stmts_in : list[indra.statements.Statement]
        A list of statements to filter.
    gene_list : list[str]
        A list of gene symbols to filter for.
    policy : str
        The policy to apply when filtering for the list of genes. "one": keep
        statements that contain at least one of the list of genes and
        possibly others not in the list "all": keep statements that only
        contain genes given in the list
    save : Optional[str]
        The name of a pickle file to save the results (stmts_out) into.

    Returns
    -------
    stmts_out : list[indra.statements.Statement]
        A list of filtered statements.
    """
    if policy not in ('one', 'all'):
        logger.error('Policy %s is invalid, not applying filter.' % policy)
    genes_str = ', '.join(gene_list)
    logger.info('Filtering %d statements for ones containing: %s...' %
                (len(stmts_in), genes_str))
    stmts_out = []
    if policy == 'one':
        for st in stmts_in:
            found_gene = False
            for agent in st.agent_list():
                if agent is not None:
                    if agent.name in gene_list:
                        found_gene = True
                        break
            if found_gene:
                stmts_out.append(st)
    elif policy == 'all':
        for st in stmts_in:
            found_genes = True
            for agent in st.agent_list():
                if agent is not None:
                    if agent.name not in gene_list:
                        found_genes = False
                        break
            if found_genes:
                stmts_out.append(st)
    logger.info('%d statements after filter...' % len(stmts_out))
    dump_pkl = kwargs.get('save')
    if dump_pkl:
        dump_statements(stmts_out, dump_pkl)
    return stmts_out

def filter_human_only(stmts_in, **kwargs):
    """Filter out statements that are not grounded to human genes.

    Parameters
    ----------
    stmts_in : list[indra.statements.Statement]
        A list of statements to filter.
    save : Optional[str]
        The name of a pickle file to save the results (stmts_out) into.

    Returns
    -------
    stmts_out : list[indra.statements.Statement]
        A list of filtered statements.

    """
    dump_pkl = kwargs.get('save')
    logger.info('Filtering %d statements for human genes only...' %
                len(stmts_in))
    stmts_out = []
    for st in stmts_in:
        human_genes = True
        for agent in st.agent_list():
            if agent is not None:
                upid = agent.db_refs.get('UP')
                if upid and not uniprot_client.is_human(upid):
                    human_genes = False
                    break
        if human_genes:
            stmts_out.append(st)
    logger.info('%d statements after filter...' % len(stmts_out))
    if dump_pkl:
        dump_statements(stmts_out, dump_pkl)
    return stmts_out

def filter_direct(stmts_in, **kwargs):
    """Filter to statements that are direct interactions

    Parameters
    ----------
    stmts_in : list[indra.statements.Statement]
        A list of statements to filter.
    save : Optional[str]
        The name of a pickle file to save the results (stmts_out) into.

    Returns
    -------
    stmts_out : list[indra.statements.Statement]
        A list of filtered statements.
    """
    def get_is_direct(stmt):
        """Returns true if there is evidence that the statement is a direct
        interaction.

        If any of the evidences associated with the statement
        indicates a direct interatcion then we assume the interaction
        is direct. If there is no evidence for the interaction being indirect
        then we default to direct.
        """
        any_indirect = False
        for ev in stmt.evidence:
            if ev.epistemics.get('direct') is True:
                return True
            elif ev.epistemics.get('direct') is False:
                # This guarantees that we have seen at least
                # some evidence that the statement is indirect
                any_indirect = True
        if any_indirect:
            return False
        return True
    logger.info('Filtering %d statements to direct ones...' % len(stmts_in))
    stmts_out = []
    for st in stmts_in:
        if get_is_direct(st):
            stmts_out.append(st)
    logger.info('%d statements after filter...' % len(stmts_out))
    dump_pkl = kwargs.get('save')
    if dump_pkl:
        dump_statements(stmts_out, dump_pkl)
    return stmts_out

def filter_evidence_source(stmts_in, source_apis, policy='one', **kwargs):
    """Filter to statements that have evidence from a given set of sources.

    Parameters
    ----------
    stmts_in : list[indra.statements.Statement]
        A list of statements to filter.
    source_apis : list[str]
        A list of sources to filter for. Examples: biopax, bel, reach
    policy : Optional[str]
        If 'one', a statement that hase evidence from any of the sources is
        kept. If 'all', only those statements are kept which have evidence
        from all the input sources specified in source_apis.
        If 'none', only those statements are kept that don't have evidence
        from any of the sources specified in source_apis.
    save : Optional[str]
        The name of a pickle file to save the results (stmts_out) into.

    Returns
    -------
    stmts_out : list[indra.statements.Statement]
        A list of filtered statements.
    """
    logger.info('Filtering %d statements to evidence source: %s...' %
                (len(stmts_in), ', '.join(source_apis)))
    stmts_out = []
    for st in stmts_in:
        sources = set([ev.source_api for ev in st.evidence])
        if policy == 'one':
            if sources.intersection(source_apis):
                stmts_out.append(st)
        if policy == 'all':
            if sources.intersection(source_apis) == set(source_apis):
                stmts_out.append(st)
        if policy == 'none':
            if not sources.intersection(source_apis):
                stmts_out.append(st)
    logger.info('%d statements after filter...' % len(stmts_out))
    dump_pkl = kwargs.get('save')
    if dump_pkl:
        dump_statements(stmts_out, dump_pkl)
    return stmts_out

def filter_top_level(stmts_in, **kwargs):
    """Filter to statements that are at the top-level of the hierarchy.

    Here top-level statements correspond to most specific ones.

    Parameters
    ----------
    stmts_in : list[indra.statements.Statement]
        A list of statements to filter.
    save : Optional[str]
        The name of a pickle file to save the results (stmts_out) into.

    Returns
    -------
    stmts_out : list[indra.statements.Statement]
        A list of filtered statements.
    """
    logger.info('Filtering %d statements for top-level' % len(stmts_in))
    stmts_out = [st for st in stmts_in if not st.supports]
    logger.info('%d statements after filter...' % len(stmts_out))
    dump_pkl = kwargs.get('save')
    if dump_pkl:
        dump_statements(stmts_out, dump_pkl)
    return stmts_out


def expand_families(stmts_in, **kwargs):
    """Expand Bioentities Agents to individual genes.

    Parameters
    ----------
    stmts_in : list[indra.statements.Statement]
        A list of statements to expand.
    save : Optional[str]
        The name of a pickle file to save the results (stmts_out) into.

    Returns
    -------
    stmts_out : list[indra.statements.Statement]
        A list of expanded statements.
    """
    logger.info('Expanding families on %d statements...' % len(stmts_in))
    expander = Expander(hierarchies)
    stmts_out = expander.expand_families(stmts_in)
    logger.info('%d statements after expanding families...' % len(stmts_out))
    dump_pkl = kwargs.get('save')
    if dump_pkl:
        dump_statements(stmts_out, dump_pkl)
    return stmts_out

def reduce_activities(stmts_in, **kwargs):
    """Reduce the activity types in a list of statements

    Parameters
    ----------
    stmts_in : list[indra.statements.Statement]
        A list of statements to reduce activity types in.
    save : Optional[str]
        The name of a pickle file to save the results (stmts_out) into.

    Returns
    -------
    stmts_out : list[indra.statements.Statement]
        A list of reduced activity statements.
    """
    logger.info('Reducing activities on %d statements...' % len(stmts_in))
    stmts_out = [deepcopy(st) for st in stmts_in]
    ml = MechLinker(stmts_out)
    ml.get_activities()
    ml.reduce_activities()
    stmts_out = ml.statements
    dump_pkl = kwargs.get('save')
    if dump_pkl:
        dump_statements(stmts_out, dump_pkl)
    return stmts_out

def strip_agent_context(stmts_in, **kwargs):
    """Strip any context on agents within each statement.

    Parameters
    ----------
    stmts_in : list[indra.statements.Statement]
        A list of statements whose agent context should be stripped.
    save : Optional[str]
        The name of a pickle file to save the results (stmts_out) into.

    Returns
    -------
    stmts_out : list[indra.statements.Statement]
        A list of stripped statements.
    """
    logger.info('Stripping agent context on %d statements...' % len(stmts_in))
    stmts_out = []
    for st in stmts_in:
        new_st = deepcopy(st)
        for agent in new_st.agent_list():
            if agent is None:
                continue
            agent.mods = []
            agent.mutations = []
            agent.activity = None
            agent.location = None
            agent.bound_conditions = []
        stmts_out.append(new_st)
    dump_pkl = kwargs.get('save')
    if dump_pkl:
        dump_statements(stmts_out, dump_pkl)
    return stmts_out

def dump_stmt_strings(stmts, fname):
    """Save printed statements in a file.

    Parameters
    ----------
    stmts_in : list[indra.statements.Statement]
        A list of statements to save in a text file.
    fname : Optional[str]
        The name of a text file to save the printed statements into.
    """
    with open(fname, 'wb') as fh:
        for st in stmts:
            fh.write(('%s\n' % st).encode('utf-8'))

if __name__ == '__main__':
    if len(sys.argv) < 3:
        logger.error('Usage: assemble_corpus.py <pickle_file> <output_folder>')
        sys.exit()
    stmts_fname = sys.argv[1]
    out_folder = sys.argv[2]

    stmts = load_statements(stmts_fname)

    logger.info('All statements: %d' % len(stmts))

    cache_pkl = os.path.join(out_folder, 'mapped_stmts.pkl')
    options = {'save': cache_pkl, 'do_rename': True}
    stmts = map_grounding(stmts, **options)

    cache_pkl = os.path.join(out_folder, 'sequence_valid_stmts.pkl')
    options = {'save': cache_pkl}
    mapped_stmts = map_sequence(stmts, **options)

    be = BeliefEngine()
    pa = Preassembler(hierarchies, mapped_stmts)

    cache_pkl = os.path.join(out_folder, 'unique_stmts.pkl')
    options = {'save': cache_pkl}
    unique_stmts = run_preassembly_duplicate(pa, be, **options)

    cache_pkl = os.path.join(out_folder, 'top_stmts.pkl')
    options = {'save': cache_pkl}
    stmts = run_preassembly_related(pa, be, **options)
